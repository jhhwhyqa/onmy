# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

import re
import time
import os
import inflection
import copy

from datetime import date
import threading
from module.device.device import Device
from typing import Any
from datetime import datetime, timedelta
from pathlib import Path
from cached_property import cached_property
from threading import Thread
from multiprocessing.queues import Queue
from module.config.config import Config
from module.device.env import IS_WINDOWS
from module.base.utils import load_module
from module.base.decorator import del_cached_property
from module.logger import logger
from module.exception import *
from module.server.i18n import I18n
from module.image.rpc import ensure_image_server_ready, get_image_client
from module.ocr.rpc import ensure_ocr_server_ready
from module.script import ScriptRuntimeController, ScriptRuntimeDecision
from tasks.Restart.server_update import delay_pending_tasks_for_server_update, is_server_update_window
from module.server.log_service import build_error_log_dir_name

_log_switch_lock = threading.Lock()#线程锁


class Script:
    def __init__(self, config_name: str ='oas') -> None:
        logger.hr('Start', level=0)
        self.state_queue: Queue = None
        self._emulator_down = False
        self.runtime = ScriptRuntimeController(self)
        self.config_name = config_name
        # Skip first restart
        self.is_first_task = True
        # Failure count of tasks
        # Key: str, task name, value: int, failure count
        self.failure_record = {}
        self.last_task_runtime_outcome: dict[str, Any] | None = None
        self.task_hoarding_until: datetime | None = None
        self.task_hoarding_released = False
        # 最近一次错误现场目录，用于错误推送附带截图
        self._last_error_log_dir: str | None = None
        self._last_error_log_task: str | None = None
        # 运行loop的线程
        self.loop_thread: Thread = None

    @cached_property
    def config(self) -> "Config":
        try:
            from module.config.config import Config
            config = Config(config_name=self.config_name)
            return config
        except RequestHumanTakeover:
            logger.critical('Request human takeover')
            exit(1)
        except Exception as e:
            logger.exception(e)
            exit(1)

    @cached_property
    def device(self) -> Device | None:
        try:
            from module.device.device import Device
            device = Device(config=self.config)
            return device
        except RequestHumanTakeover:
            logger.critical('Request human takeover')
            exit(1)
        except Exception as e:
            logger.exception(e)
            exit(1)

    @cached_property
    def checker(self):
        """
        占位函数，在OAS中是检查服务器是否正常的
        :return:
        """
        return None

    def save_error_log(self) -> str | None:
        """
        保存错误现场到 ./log/error/<script_name>_<timestamp_ms>。

        保存内容包括:
        - 最近一段截图, 文件名为时间戳 PNG。
        - 当前脚本日志的截取内容, 文件名为 log.txt。

        说明:
        - 新错误目录名会带上脚本名, 便于前端区分不同脚本产生的错误。
        - 目录名和脚本名都会经过统一净化, 避免路径注入。
        - 返回错误现场目录；未启用保存或保存失败时返回 None。
        """
        from module.base.utils import save_image
        from module.handler.sensitive_info import (handle_sensitive_image,
                                                   handle_sensitive_logs)
        self._last_error_log_dir = None
        if not self.config.script.error.save_error:
            return None
        if not os.path.exists('./log/error'):
            os.mkdir('./log/error')
        # 用统一规则生成错误目录名, 目录格式为 <script_name>_<timestamp_ms>。
        folder_name = build_error_log_dir_name(self.config_name, int(time.time() * 1000))
        folder = f'./log/error/{folder_name}'
        logger.warning(f'Saving error: {folder}')
        os.mkdir(folder)
        for data in self.device.screenshot_deque:
            image_time = datetime.strftime(data['time'], '%Y-%m-%d_%H-%M-%S-%f')
            image = handle_sensitive_image(data['image'])
            save_image(image, f'{folder}/{image_time}.png')
        with open(logger.log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            start = 0
            for index, line in enumerate(lines):
                line = line.strip(' \r\t\n')
                if re.match('^═{15,}$', line):
                    start = index
            lines = lines[start - 2:]
            lines = handle_sensitive_logs(lines)
        with open(f'{folder}/log.txt', 'w', encoding='utf-8') as f:
            f.writelines(lines)
        self._last_error_log_dir = folder
        return folder

    MAX_ERROR_PUSH_IMAGES = 5

    def _safe_save_error_log(self) -> str | None:
        """保存错误现场；失败时只记录日志，不影响后续推送。"""
        try:
            return self.save_error_log()
        except Exception as e:
            logger.warning(f'Failed to save error log for notification: {e}')
            return None

    def _error_push_attachments(self, folder: str | None) -> tuple[list[bytes], list[str]]:
        """读取错误现场截图；仅当当前推送渠道支持附件时返回。"""
        if not folder or not self.config.notifier.supports_images:
            return [], []
        error_dir = Path(folder)
        if not error_dir.is_dir():
            return [], []
        images: list[bytes] = []
        filenames: list[str] = []
        screenshots = sorted(error_dir.glob('*.png'))[-self.MAX_ERROR_PUSH_IMAGES:]
        for screenshot in screenshots:
            try:
                images.append(screenshot.read_bytes())
                filenames.append(screenshot.name)
            except OSError as e:
                logger.warning(f'Read error screenshot failed: {screenshot}: {e}')
        return images, filenames

    def _push_error(self, command: str, content: str, folder: str | None = None) -> None:
        """推送错误通知；支持的渠道附带错误现场截图。"""
        images, filenames = self._error_push_attachments(folder)
        self.config.notifier.push(
            title=I18n.task_title(command),
            content=content,
            images=images,
            filenames=filenames,
        )

    @staticmethod
    def _log_image_cache_stats(stage: str = '') -> None:
        """
        输出一行图像缓存摘要，用于判断性能优化的着力点。

        数据来自图像服务端的 `get_server_info()`，是服务启动以来的累计计数。
        任务开始与结束各打一行，两者相减即为本次任务的增量。

        Args:
            stage: 标记这条摘要属于哪个阶段，如 `start:TrueOrochi`。
        """
        try:
            info = get_image_client().get_server_info()
        except Exception as e:
            logger.debug(f'Image cache stats unavailable: {e}')
            return

        stats = info.get('cache_stats') or {}
        # 文件日志按 160 列截断，这里必须保持紧凑，否则尾部字段会被截掉。
        label = f'[{stage}]' if stage else ''
        logger.info(
            f'ImageCache{label} '
            f"frames={info.get('frame_cache_count')} tpl={info.get('template_cache_count')} "
            f"fh={stats.get('frame_hits', 0)} fm={stats.get('frame_misses', 0)} "
            f"th={stats.get('template_hits', 0)} tm={stats.get('template_misses', 0)} "
            f"exp={stats.get('template_expired', 0)}"
        )

    def wait_until(self, future):
        """
        Wait until a specific time.

        Args:
            future (datetime):

        Returns:
            bool: True if wait finished, False if config changed.
        """
        future = future + timedelta(seconds=1)
        self.config.start_watching()
        while 1:
            if datetime.now() > future:
                return True
            # if self.stop_event is not None:
            #     if self.stop_event.is_set():
            #         logger.info("Update event detected")
            #         logger.info(f"[{self.config_name}] exited. Reason: Update")
            #         exit(0)

            time.sleep(5)

            if self.config.should_reload():
                return False

    def _hoard_next_task(self, task, now: datetime):
        """在空闲时延迟首个到期任务，窗口内到达的任务一并等待。"""
        duration = self.config.script.optimization.task_hoarding_duration
        if duration <= 0 or not self.config.pending_task:
            self.task_hoarding_until = None
            self.task_hoarding_released = False
            return task

        if (self.config.model.running_task or self.task_hoarding_released
                or (self.is_first_task and task.command == 'Restart')
                or (task.next_run > now and self.task_hoarding_until is None)):
            return task

        if self.task_hoarding_until is None:
            self.task_hoarding_until = now + timedelta(minutes=duration)
            logger.info(
                f"Task hoarding started for {duration:g} minutes, "
                f"release at {self.task_hoarding_until.strftime('%Y-%m-%d %H:%M:%S')}"
            )

        if now < self.task_hoarding_until:
            task = copy.deepcopy(task)
            task.next_run = max(self.task_hoarding_until, task.next_run)
            logger.info(
                f"Task hoarding active, defer pending tasks until "
                f"{self.task_hoarding_until.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return task

        self.task_hoarding_until = None
        self.task_hoarding_released = True
        logger.info("Task hoarding window ended, resume scheduled task execution")
        return task

    def get_next_task(self) -> str:
        """
        获取下一个任务的名字, 大驼峰。
        :return:
        """
        while True:
            task = self.config.get_next()
            now = datetime.now()
            task = self._hoard_next_task(task, now)
            self.config.task = task
            if self.state_queue:
                self.state_queue.put({"schedule": self.config.get_schedule_data()})
            # 任务时间到了返回任务名称
            if task.next_run <= now:
                return task.command
            # 根据策略执行等待逻辑
            wait_until = task.next_run
            if self.task_hoarding_until and self.config.waiting_task:
                wait_until = min(wait_until, self.config.waiting_task[0].next_run)
            decision = self.runtime.handle_wait_during_idle(wait_until)
            if decision == ScriptRuntimeDecision.RESCHEDULE:
                logger.info('Idle wait requested scheduler refresh, reload config and reschedule')
                del_cached_property(self, "config")
            elif decision == ScriptRuntimeDecision.FAILED:
                logger.warning('Idle wait preparation failed, reload config and retry scheduling')
                del_cached_property(self, "config")

    def exception_handler(self, e: Exception, command: str) -> None:
        # 处理御魂溢出
        from tasks.Utils.post_diagnotor import PostDiagnotor, AnalyzeType
        image = getattr(self.device, 'image', None)
        # image为None则不做处理
        if image is None:
            return
        analyse_type = PostDiagnotor().handle(e=e, command=command, image=image)
        if analyse_type == AnalyzeType.SoulOverflow:
            self.config.task_call('SoulsTidy')
            time.sleep(1)

    def _reset_task_runtime_outcome(self) -> None:
        self.last_task_runtime_outcome = None
        if 'config' in self.__dict__:
            self.config.task_runtime_outcome = None

    def _set_task_runtime_outcome(self, task: str, status: str, wait_until: datetime | None = None) -> None:
        outcome = {
            'task': task,
            'status': status,
        }
        if wait_until is not None:
            outcome['wait_until'] = wait_until
        self.last_task_runtime_outcome = outcome
        if 'config' in self.__dict__:
            self.config.task_runtime_outcome = outcome

    def _capture_task_runtime_outcome(self, command: str) -> None:
        outcome = getattr(self.config, 'task_runtime_outcome', None)
        self.last_task_runtime_outcome = outcome if isinstance(outcome, dict) else None
        if self.last_task_runtime_outcome is None:
            return
        status = self.last_task_runtime_outcome.get('status')
        if status == 'server_update_delayed':
            wait_until = self.last_task_runtime_outcome.get('wait_until')
            logger.info(f'{command} runtime outcome: server_update_delayed (wait_until={wait_until})')
            if isinstance(wait_until, datetime):
                self.runtime.server_update_wait_until = wait_until
                self.runtime.server_update_wait_log_until = None
            return
        if command != 'Restart':
            return
        if status == 'recovered':
            logger.info('Restart runtime outcome: recovered')
            return
        logger.info(f'Restart runtime outcome: {status}')

    def _delay_tasks_for_server_update(self, task: str, reason: str) -> bool:
        if not is_server_update_window():
            return False

        delay_target = delay_pending_tasks_for_server_update(self.config, reason=reason)
        self._set_task_runtime_outcome(task=task, status='server_update_delayed', wait_until=delay_target)
        return True

    def run(self, command: str) -> bool:
        """
        :param command:  大写驼峰命名的任务名字
        :return:
        """
        if command == 'start' or command == 'goto_main':
            logger.error(f'Invalid command `{command}`')

        self._reset_task_runtime_outcome()
        try:
            self.device.screenshot()
            module_name = 'script_task'
            module_path = str(Path.cwd() / 'tasks' / command / (module_name + '.py'))
            logger.info(f'module_path: {module_path}, module_name: {module_name}')
            task_module = load_module(module_name, module_path)
            task_module.ScriptTask(config=self.config, device=self.device).run()
        except Exception as e:
            return self._handle_task_exception(e, command)
        return False

    def loop(self):
        """
        Main loop of scheduler.
        :return:
        """
        with _log_switch_lock:
            logger.set_file_logger(self.config_name, do_cleanup=True)
        start_day = date.today()
        logger.info(f'Start scheduler loop: {self.config_name}')
        self.config.model.running_task = ''

        # Update GUI 防呆, 读取设置并立刻显示后台模拟器到前台
        if not self.config.script.device.run_background_only and IS_WINDOWS:
            from module.device.platform2.platform_windows import minimize_by_name, show_window_by_name
            target_window_name = self.config.script.device.handle  # 在这里输入你的具体窗口名称
            if self.config.script.device.emulator_window_minimize:
                minimize_by_name(target_window_name)
                logger.info(f'重新显示: {target_window_name}')
            else:
                show_window_by_name(target_window_name)
                
        while 1:
            if date.today() > start_day:
                with _log_switch_lock:
                    logger.set_file_logger(self.config_name, do_cleanup=True)
                start_day = date.today()

            task = ""
            try:
                # Get task
                task = self.get_next_task()
                # Skip first restart
                if self.is_first_task and task == 'Restart':
                    logger.info('Skip task `Restart` at scheduler start')
                    self.config.task_delay(task='Restart', success=True, server=True)
                    del_cached_property(self, 'config')
                    continue
                decision = self.runtime.prepare_task_execution(task)
            except Exception as e:
                self._handle_task_exception(e, task)
                # 本轮 prepare 失败,重新调度
                del_cached_property(self, 'config')
                continue

            if decision == ScriptRuntimeDecision.RESCHEDULE:
                logger.info(f'Runtime preparation for `{task}` requested reschedule, reload config and retry scheduling')
                del_cached_property(self, 'config')
                continue
            if decision == ScriptRuntimeDecision.FAILED:
                logger.warning(f'Runtime preparation for `{task}` failed, reload config and retry scheduling')
                del_cached_property(self, 'config')
                continue

            # Run
            logger.info(f'Scheduler: Start task `{task}`')
            self._log_image_cache_stats('S')
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            logger.hr(task, level=0)
            self.config.model.running_task = task
            success = self.run(inflection.camelize(task))
            self.config.model.running_task = ''
            logger.info(f'Scheduler: End task `{task}`')
            self._log_image_cache_stats('E')
            self.is_first_task = False

            # Check failures
            # failed = deep_get(self.failure_record, keys=task, default=0)
            failed = self.failure_record[task] if task in self.failure_record else 0
            failed = 0 if success else failed + 1
            # deep_set(self.failure_record, keys=task, value=failed)
            self.failure_record[task] = failed
            if failed >= 3:
                logger.critical(f"Task `{task}` failed 3 or more times.")
                logger.critical("Possible reason #1: You haven't used it correctly. "
                                "Please read the help text of the options.")
                logger.critical("Possible reason #2: There is a problem with this task. "
                                "Please contact developers or try to fix it yourself.")
                logger.critical('Request human takeover')
                # 添加失败三次的推送通知；如果本任务留下过错误现场，
                # 一并附带截图（仅支持附件的渠道）。
                error_log_dir = (
                    self._last_error_log_dir
                    if self._last_error_log_task == task else None
                )
                self._push_error(
                    task,
                    f"<{self.config_name}> 任务连续失败三次，请上线查看",
                    error_log_dir,
                )
                # 关闭模拟器
                if self.config.script.error.error_repeated:
                    self.device.emulator_stop()
                exit(1)

            if success:
                del_cached_property(self, 'config')
                continue
            elif self.config.script.error.handle_error:
                # self.config.task_delay(success=False)
                del_cached_property(self, 'config')
                # self.checker.check_now()
                continue
            else:
                break

    def _handle_task_exception(self, e: Exception, command: str) -> bool:
        """
        统一处理任务执行 / 准备阶段抛出的异常。
        Returns:
            True  -> 视为正常结束或已自动恢复 (例如已 task_call('Restart')),
                     调度器继续推进
            False -> 视为失败,脚本继续运行
        对致命异常 (ScriptError / RequestHumanTakeover / 未识别 Exception)
        在内部直接 exit(1)。
        """
        if isinstance(e, TaskEnd):
            self._capture_task_runtime_outcome(command)
            return True

        if isinstance(e, GameNotRunningError):
            logger.warning(e)
            self.exception_handler(e=e, command=command)
            self.config.task_call('Restart')
            return True

        if isinstance(e, (GameStuckError, GameTooManyClickError)):
            logger.error(e)
            error_log_dir = self._safe_save_error_log()
            if error_log_dir:
                self._last_error_log_task = command
            self.exception_handler(e=e, command=command)
            logger.warning(f'Game stuck, {self.device.package} will be restarted in 10 seconds')
            logger.warning('If you are playing by hand, please stop OAS')
            self._push_error(
                command,
                f"<{self.config_name}> GameStuckError or GameTooManyClickError",
                error_log_dir,
            )
            self.config.task_call('Restart')
            self.device.sleep(10)
            return False

        if isinstance(e, GameBugError):
            logger.warning(e)
            error_log_dir = self._safe_save_error_log()
            if error_log_dir:
                self._last_error_log_task = command
            self.exception_handler(e=e, command=command)
            logger.warning('An error has occurred in Onmyoji game client, OAS is unable to handle')
            logger.warning(f'Restarting {self.device.package} to fix it')
            self.config.task_call('Restart')
            self.device.sleep(10)
            return False

        if isinstance(e, GamePageUnknownError):
            logger.info('Game server may be under maintenance or network may be broken, check server status now')
            if command == 'GotoMain' and self._delay_tasks_for_server_update(
                    task=command,
                    reason='failed to goto main during morning server update window',
            ):
                logger.info('GotoMain failed during server update window, delayed pending tasks and reschedule')
                return False
            logger.critical('Game page unknown')
            error_log_dir = self._safe_save_error_log()
            if error_log_dir:
                self._last_error_log_task = command
            self.exception_handler(e=e, command=command)
            self._push_error(
                command,
                f"<{self.config_name}> GamePageUnknownError",
                error_log_dir,
            )
            self.config.task_call('Restart')
            self.device.sleep(10)
            return False

        if isinstance(e, ScriptError):
            logger.critical(e)
            self.exception_handler(e=e, command=command)
            logger.critical('This is likely to be a mistake of developers, but sometimes just random issues')
            error_log_dir = self._safe_save_error_log()
            if error_log_dir:
                self._last_error_log_task = command
            self._push_error(
                command,
                f"<{self.config_name}> ScriptError",
                error_log_dir,
            )
            exit(1)

        if isinstance(e, RequestHumanTakeover):
            logger.critical(e)
            self.exception_handler(e=e, command=command)
            logger.critical('Request human takeover')
            error_log_dir = self._safe_save_error_log()
            if error_log_dir:
                self._last_error_log_task = command
            self._push_error(
                command,
                f"<{self.config_name}> RequestHumanTakeover",
                error_log_dir,
            )
            exit(1)

        # generic
        logger.exception(e)
        self.exception_handler(e=e, command=command)
        error_log_dir = self._safe_save_error_log()
        if error_log_dir:
            self._last_error_log_task = command
        self._push_error(
            command,
            f"<{self.config_name}> Exception occured",
            error_log_dir,
        )
        exit(1)
        return False

    def start_loop(self) -> None:
        """
        创建一个线程，运行loop
        :return:
        """
        if self.loop_thread is None:
            self.loop_thread = Thread(target=self.loop, name='Script_loop')
            self.loop_thread.start()


if __name__ == "__main__":
    ensure_image_server_ready()
    ensure_ocr_server_ready()
    script = Script("oas1")
    script.loop()
