# This Python file uses the following encoding: utf-8
"""超鬼王门票自动获取：探索（探索+突破循环）或觉醒副本。

超鬼王期间顶栏位移，Exploration 的突破券 ROI 会读到金币，所以进度和突破券
都必须用本任务自己的规则，绘卷模式也要关掉。
"""
from __future__ import annotations

import time
from datetime import datetime, time as clock_time, timedelta

from module.exception import TaskEnd
from module.logger import logger
from tasks.EvoZone.config import UserStatus as EvoUserStatus
from tasks.EvoZone.script_task import ScriptTask as EvoZoneScriptTask
from tasks.Exploration.config import (
    AutoRotate,
    ChooseRarity,
    UpType,
    UserStatus as ExpUserStatus,
)
from tasks.Exploration.script_task import ScriptTask as ExplorationScriptTask
from tasks.MetaDemon.config import TICKET_DAILY_LIMIT, TicketFarmMode
from tasks.RealmRaid.config import WhenAttackFail
from tasks.RealmRaid.script_task import ScriptTask as RealmRaidScriptTask


class _TicketFull(Exception):
    """门票刷满，用于中断借用中的子任务。"""


class _SchedulerGuard:
    """子任务运行期间屏蔽它的 set_next_run，退出时还原。"""

    def __init__(self, config, task_name: str):
        self.config = config
        self.task_name = task_name
        self._original = None

    def __enter__(self):
        try:
            self._original = self.config.task_delay
            self.config.task_delay = lambda *a, **k: None
            logger.info(f'Suppress scheduler write of {self.task_name} during ticket farm')
        except Exception as exc:
            logger.warning(f'Cannot suppress {self.task_name} scheduler: {exc}')
            self._original = None
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._original is not None:
            try:
                self.config.task_delay = self._original
            except Exception as exc:
                logger.warning(f'Cannot restore {self.task_name} scheduler: {exc}')
        return False


class TicketFarmMixin:
    """超鬼王门票自动获取；宿主需具备 BaseTask 能力且 self.conf 是 MetaDemon。"""

    PROGRESS_READ_RETRY = 3
    # 每刷一轮回来复查进度的间隔（秒）
    PROGRESS_CHECK_INTERVAL = 5
    # 连续读不到进度的轮数上限；活动期间进度常驻，连续 15 轮读不到
    # 只可能是 OCR 服务挂了，别把用户刷票任务掐死在半路
    PROGRESS_UNREADABLE_LIMIT = 15
    # 子任务只受时间和门票进度约束，把它的挑战次数上限设成够不到的大数
    SUB_TASK_UNLIMITED_COUNT = 100000
    # 子任务时限字段是 datetime.time（子任务里取 .hour/.minute），
    # 23:59:59 ≈ 近 24 小时，刷票只由门票进度叫停
    SUB_TASK_UNLIMITED_TIME = clock_time(hour=23, minute=59, second=59)
    # 进度素材，奖励页优先，探索页保底
    PROGRESS_RULES = (
        'O_MD_TICKET_PROGRESS',
        'O_MD_TICKET_PROGRESS_EXPLORATION',
    )

    # ---------------------------------------------------------------- 进度读取

    _last_progress: tuple[int, int] = (-1, -1)

    def register_progress_hooks(self) -> None:
        """在探索页挂进入 hook；奖励页走战斗流程，hook 收不到。"""
        from tasks.GameUi.page import page_exploration

        target = self.navigator.resolve_page(page_exploration)
        if target is None:
            logger.warning('Cannot resolve page_exploration, skip ticket progress hook')
            return
        target.add_enter_success_hooks(self._capture_ticket_progress)

    def _capture_ticket_progress(self, task=None, screenshot: bool = False) -> bool:
        """读一次进度存到 `_last_progress`，读到就打日志。"""
        current, total = self._read_progress_once(screenshot=screenshot)
        if total <= 0:
            return False
        # OCR 多识别一位时 current 会超出上限，丢弃这次读数等下一帧
        if current > self._progress_target(total):
            logger.warning(
                f'Ticket progress {current}/{total} exceeds limit, treat as unreadable'
            )
            return False
        self._last_progress = (current, total)
        logger.info(f'超鬼王门票进度: {current}/{total}')
        return True

    def _read_progress_once(self, screenshot: bool = True) -> tuple[int, int]:
        """按 PROGRESS_RULES 顺序读一次进度，读不到返回 (-1, -1)。"""
        if screenshot:
            self.screenshot()
        for rule_name in self.PROGRESS_RULES:
            rule = getattr(self, rule_name, None)
            if rule is None:
                continue
            # log=False：奖励页每帧都会调，OCR 内部日志会刷屏
            current, remain, total = rule.ocr(self.device.image, log=False)
            if total > 0:
                return current, total
        return -1, -1

    def _ensure_progress_page(self) -> None:
        """进度只在探索页/奖励页显示，庭院读不到，先切到探索页。"""
        from tasks.GameUi.page import page_exploration

        self.goto_page(page_exploration)

    def read_ticket_progress(self, goto_page: bool = True) -> tuple[int, int]:
        """带重试地读进度，返回 (当前, 上限)，失败返回 (-1, -1)。"""
        if all(getattr(self, name, None) is None for name in self.PROGRESS_RULES):
            logger.warning('No ticket progress rule annotated, cannot read progress')
            return -1, -1
        if goto_page:
            self._ensure_progress_page()
        best = (-1, -1)
        for attempt in range(1, self.PROGRESS_READ_RETRY + 1):
            current, total = self._read_progress_once(screenshot=attempt == 1)
            target = self._progress_target(total)
            # OCR 多识别一位时 current 会超出上限，这次读数直接丢弃
            if target > 0 and current <= target:
                if current > best[0]:
                    best = (current, total)
                if current == target:
                    break
            elif target > 0:
                logger.warning(f'Ignored OCR result {current}/{total}: exceeds limit')
            if attempt < self.PROGRESS_READ_RETRY:
                time.sleep(0.3)
        logger.info(f'超鬼王门票进度: {best[0]}/{best[1]}')
        return best

    def _is_progress_full(self, current: int, total: int) -> bool:
        """进度是否刷满：必须是 current == 上限，超过上限视为 OCR 误读。"""
        if total <= 0 or current < 0:
            return False
        target = self._progress_target(total)
        if target <= 0:
            return False
        if current > target:
            # OCR 多识别一位（如 39/50 读成 139/50），不能当成已满
            logger.warning(
                f'Ticket progress {current}/{total} exceeds limit {target}, ignore'
            )
            return False
        return current == target

    @staticmethod
    def _progress_target(total: int) -> int:
        """把页面读到上限换算成目标值；上限固定 50，误读成更大值时按 50 算。"""
        if total <= 0:
            return -1
        return min(TICKET_DAILY_LIMIT, total)

    def ticket_progress_full(self) -> bool:
        """门票是否已刷满；读不到按未满处理。"""
        current, total = self.read_ticket_progress()
        if total <= 0:
            logger.warning('Cannot read ticket progress, treat as not full')
            return False
        full = self._is_progress_full(current, total)
        logger.info(f'超鬼王门票进度: {current}/{total}, 已满={full}')
        return full

    # ---------------------------------------------------------------- 入口

    def ensure_tickets(self) -> bool:
        """门票不足时按配置刷票；返回 True 表示可以继续打鬼王。

        刷票不设时间上限，只看门票进度：刷满 50/50 为止。
        防失控护栏：探索侧连续读不到进度会主动停（PROGRESS_UNREADABLE_LIMIT），
        子任务侧由战斗 hook 的 unreadable 逻辑兜底。
        """
        con = self.conf.meta_demon_ticket_farm
        if not con.ticket_farm_enable:
            return True
        logger.hr('MetaDemon ticket farm', 1)
        self.register_progress_hooks()
        if self.ticket_progress_full():
            logger.info('Ticket already full, skip farming')
            self._back_to_main()
            return True

        try:
            match con.ticket_farm_mode:
                case TicketFarmMode.EVO_ZONE:
                    self.farm_ticket_by_evo_zone()
                case _:
                    self.farm_ticket_by_exploration()
        except (_TicketFull, TaskEnd) as exc:
            # 刷满或子任务正常结束，都要吞掉，否则会打断超鬼王主流程
            logger.info(f'Ticket farm stopped: {type(exc).__name__}')
        except Exception as exc:
            logger.warning(f'Ticket farm raised: {type(exc).__name__}: {exc}')

        if self.ticket_progress_full():
            logger.info('Ticket farm finished, start MetaDemon')
            self._back_to_main()
            return True
        logger.warning('Ticket still not full, stop this run and retry later')
        self._back_to_main()
        return False

    def _back_to_main(self) -> None:
        """回主界面；从突破页进的式神录回不到超鬼王，必须从主界面重新出发。"""
        from tasks.GameUi.page import page_main

        logger.info('Back to main before starting MetaDemon')
        self.goto_page(page_main)

    # ---------------------------------------------------------------- 调度隔离

    def _sub_task_scheduler_guard(self, task_name: str):
        """让子任务运行期间不写回它自己的排期。"""
        return _SchedulerGuard(self.config, task_name)

    def _attach_progress_hook(self, sub_task) -> None:
        """把进度采集挂到子任务实例上；宿主上的覆写对子任务不生效。"""
        from tasks.GameUi.page import page_exploration

        host = self

        def capture(task=None) -> bool:
            return host._capture_ticket_progress()

        navigator = getattr(sub_task, 'navigator', None)
        if navigator is None:
            logger.warning('Sub task has no navigator, ticket progress not captured')
            return

        target = navigator.resolve_page(page_exploration)
        if target is not None:
            target.add_enter_success_hooks(capture)

        # 奖励页在子任务的 run_general_battle 里，只能包它的 handler
        original = sub_task._handle_reward

        def _handle_reward(context, config):
            # 先让父类点一下奖励页，进度条才会显示出来
            action = original(context, config)
            # 只有真的读到才标记完成，读不到就留到下一帧重试
            if 'ticket_progress' not in context.call_behavior_state.done:
                if host._capture_ticket_progress(screenshot=True):
                    context.call_behavior_state.done.add('ticket_progress')
                    current, total = host._last_progress
                    if host._is_progress_full(current, total):
                        logger.info('Ticket full, stop sub task')
                        raise _TicketFull()
            return action

        sub_task._handle_reward = _handle_reward

        # 探索子任务的 page_reward 是 lambda，不走 _handle_reward，单独包
        if hasattr(sub_task, 'check_exit'):
            self._wrap_exploration_exit(sub_task)

    def _wrap_exploration_exit(self, sub_task) -> None:
        """包住 check_exit，票满时打断探索子任务（它的 page_reward 是 lambda，不走 _handle_reward）。"""
        host = self
        original = sub_task.check_exit
        checked = []

        def check_exit(current_page) -> bool:
            if original(current_page):
                return True
            # 只有真的读到才标记完成，读不到就留到下一帧重试
            if not checked:
                if host._capture_ticket_progress(screenshot=True):
                    checked.append(1)
                    current, total = host._last_progress
                    if host._is_progress_full(current, total):
                        logger.info('Ticket full, stop exploration sub task')
                        raise _TicketFull()
            return False

        sub_task.check_exit = check_exit

    # ---------------------------------------------------------------- 觉醒副本

    def farm_ticket_by_evo_zone(self) -> None:
        """用觉醒副本刷票，层数和麒麟取本任务配置，结束后恢复用户配置。

        不设时间上限，只受门票进度约束（进度满时战斗 hook 抛 _TicketFull）。
        """
        con = self.conf.meta_demon_ticket_farm
        logger.hr('Farm ticket by EvoZone', 2)
        evo_conf = self.config.evo_zone
        backup = {
            'user_status': evo_conf.evo_zone_config.user_status,
            'layer': evo_conf.evo_zone_config.layer,
            'kirin_type': evo_conf.evo_zone_config.kirin_type,
            'limit_count': evo_conf.evo_zone_config.limit_count,
            'limit_time': evo_conf.evo_zone_config.limit_time,
        }
        try:
            evo_conf.evo_zone_config.user_status = EvoUserStatus.ALONE
            evo_conf.evo_zone_config.layer = con.layer
            evo_conf.evo_zone_config.kirin_type = con.kirin_type
            # 刷票只看门票进度，不受子任务的挑战次数/时限约束
            evo_conf.evo_zone_config.limit_count = self.SUB_TASK_UNLIMITED_COUNT
            evo_conf.evo_zone_config.limit_time = self.SUB_TASK_UNLIMITED_TIME
            with self._sub_task_scheduler_guard('EvoZone'):
                task = EvoZoneScriptTask(self.config, self.device)
                self._attach_progress_hook(task)
                task.run()
        finally:
            evo_conf.evo_zone_config.user_status = backup['user_status']
            evo_conf.evo_zone_config.layer = backup['layer']
            evo_conf.evo_zone_config.kirin_type = backup['kirin_type']
            evo_conf.evo_zone_config.limit_count = backup['limit_count']
            evo_conf.evo_zone_config.limit_time = backup['limit_time']

    # ---------------------------------------------------------------- 探索副本

    def farm_ticket_by_exploration(self) -> None:
        """探索刷票；默认探索+突破循环，开了 skip_realm_raid 就只打探索。

        不设时间上限，每轮间隙复查门票进度，刷满即回。
        """
        con = self.conf.meta_demon_ticket_farm
        logger.hr('Farm ticket by Exploration', 2)
        exp_conf = self.config.exploration
        backup = {
            'user_status': exp_conf.exploration_config.user_status,
            'exploration_level': exp_conf.exploration_config.exploration_level,
            'auto_rotate': exp_conf.exploration_config.auto_rotate,
            'choose_rarity': exp_conf.exploration_config.choose_rarity,
            'up_type': exp_conf.exploration_config.up_type,
            'collect_paper_reward': exp_conf.exploration_config.collect_paper_reward,
            'minions_cnt': exp_conf.exploration_config.minions_cnt,
            'scrolls_enable': exp_conf.scrolls.scrolls_enable,
            'scrolls_threshold': exp_conf.scrolls.scrolls_threshold,
            'limit_time': exp_conf.exploration_config.limit_time,
        }
        try:
            exp_conf.exploration_config.user_status = ExpUserStatus.ALONE
            exp_conf.exploration_config.exploration_level = con.exploration_level
            exp_conf.exploration_config.auto_rotate = AutoRotate.no
            exp_conf.exploration_config.choose_rarity = ChooseRarity.N
            exp_conf.exploration_config.up_type = UpType.ALL
            exp_conf.exploration_config.collect_paper_reward = True
            # 刷票只看门票进度，不受子任务的战斗次数/时限约束
            exp_conf.exploration_config.minions_cnt = self.SUB_TASK_UNLIMITED_COUNT
            exp_conf.exploration_config.limit_time = self.SUB_TASK_UNLIMITED_TIME
            # 关掉绘卷模式，避免它读错 ROI 后改掉排期
            exp_conf.scrolls.scrolls_enable = False
            exp_conf.scrolls.scrolls_threshold = con.realm_raid_threshold
            unreadable_rounds = 0
            while True:
                current, total = self.read_ticket_progress(goto_page=False)
                if total > 0:
                    unreadable_rounds = 0
                    if self._is_progress_full(current, total):
                        logger.info('Ticket full, stop exploration loop')
                        return
                else:
                    # 读不到进度时不能无限刷
                    unreadable_rounds += 1
                    logger.warning(
                        f'Ticket progress unreadable '
                        f'({unreadable_rounds}/{self.PROGRESS_UNREADABLE_LIMIT})'
                    )
                    if unreadable_rounds >= self.PROGRESS_UNREADABLE_LIMIT:
                        logger.error('Ticket progress keeps unreadable, stop farming')
                        return
                self._run_one_exploration_round()
                # 开了「只打探索」就完全跳过结界突破
                if not con.exploration_skip_realm_raid and self._realm_raid_ticket_ready():
                    self._run_one_realm_raid_round()
                time.sleep(self.PROGRESS_CHECK_INTERVAL)
        finally:
            exp_conf.exploration_config.user_status = backup['user_status']
            exp_conf.exploration_config.exploration_level = backup['exploration_level']
            exp_conf.exploration_config.auto_rotate = backup['auto_rotate']
            exp_conf.exploration_config.choose_rarity = backup['choose_rarity']
            exp_conf.exploration_config.up_type = backup['up_type']
            exp_conf.exploration_config.collect_paper_reward = backup['collect_paper_reward']
            exp_conf.exploration_config.minions_cnt = backup['minions_cnt']
            exp_conf.scrolls.scrolls_enable = backup['scrolls_enable']
            exp_conf.scrolls.scrolls_threshold = backup['scrolls_threshold']
            exp_conf.exploration_config.limit_time = backup['limit_time']

    def _run_one_exploration_round(self) -> None:
        """跑一轮探索，TaskEnd 视为正常结束。"""
        logger.info('Run one exploration round')
        try:
            with self._sub_task_scheduler_guard('Exploration'):
                task = ExplorationScriptTask(self.config, self.device)
                self._attach_progress_hook(task)
                task.run()
        except TaskEnd:
            pass

    def _realm_raid_ticket_ready(self) -> bool:
        """突破券是否达到阈值；读不到时不触发突破。"""
        con = self.conf.meta_demon_ticket_farm
        rule = getattr(self, 'O_MD_REALM_RAID_TICKET', None)
        if rule is None:
            logger.info('O_MD_REALM_RAID_TICKET is not annotated, skip realm raid')
            return False
        self.screenshot()
        current, remain, total = rule.ocr(self.device.image)
        logger.info(f'Realm raid ticket {current}/{total}, threshold {con.realm_raid_threshold}')
        if total <= 0 or current > total:
            logger.warning(f'Realm raid ticket {current}/{total} invalid, skip realm raid')
            return False
        return current >= con.realm_raid_threshold

    def _run_one_realm_raid_round(self) -> None:
        """打一轮突破。"""
        logger.hr('Run one realm raid round', 2)
        raid_conf = self.config.realm_raid
        backup = {
            'when_attack_fail': raid_conf.raid_config.when_attack_fail,
            'number_attack': raid_conf.raid_config.number_attack,
        }
        try:
            raid_conf.raid_config.when_attack_fail = WhenAttackFail.CONTINUE
            raid_conf.raid_config.number_attack = min(
                30, self.conf.meta_demon_ticket_farm.realm_raid_threshold
            )
            with self._sub_task_scheduler_guard('RealmRaid'):
                task = RealmRaidScriptTask(self.config, self.device)
                task.run()
        except TaskEnd:
            pass
        finally:
            raid_conf.raid_config.when_attack_fail = backup['when_attack_fail']
            raid_conf.raid_config.number_attack = backup['number_attack']

