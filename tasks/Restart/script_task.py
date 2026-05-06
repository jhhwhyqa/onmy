# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import datetime

from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.Login.service import LoginService
from tasks.base_task import BaseTask


class ScriptTask(BaseTask):

    def _set_runtime_outcome(self, status: str, wait_until: datetime | None = None) -> None:
        outcome = {
            'task': 'Restart',
            'status': status,
        }
        if wait_until is not None:
            outcome['wait_until'] = wait_until
        self.config.task_runtime_outcome = outcome

    def run(self) -> None:
        """
        主要就是登录的模块
        :return:
        """
        if not self.delay_pending_tasks():
            self.recover_app()
            self.finish_recovery()
        raise TaskEnd('ScriptTask end')

    def app_stop(self):
        logger.hr('App stop')
        self.device.app_stop()

    def app_start(self):
        logger.hr('App start')
        self.device.app_start()
        self.device.wait_app_start_ready()
        LoginService(config=self.config, device=self.device).app_handle_login()

    def app_restart(self):
        logger.hr('App restart')
        self.device.app_stop()
        self.app_start()

    def recover_app(self):
        if not self.device.app_is_alive():
            logger.info('Recovery branch: game process not alive and not in foreground -> full restart')
            self.app_restart()
            return

        if self.device.app_is_running():
            logger.info('Recovery branch: game process alive and in foreground -> full restart')
            self.app_restart()
            return

        logger.info('Recovery branch: game process alive but in background -> bring to foreground')
        self.app_start()

    def finish_recovery(self):
        self.set_next_run(task='Restart', success=True, finish=True, server=True)
        if self.config.model.restart.restart_config.enable_daily:
            self.config.task_call('DailyTrifles')
        self._set_runtime_outcome(status='recovered')

    def delay_pending_tasks(self) -> bool:
        """
        周三更新游戏的时候延迟
        @return:
        """
        datetime_now = datetime.now()
        if not (datetime_now.weekday() == 2 and 6 <= datetime_now.hour <= 8):
            return False
        delay_target = datetime_now.replace(hour=9, minute=0, second=0, microsecond=0)
        logger.info("The game server is updating, delay the pending tasks to 9:00")
        logger.warning('Delay pending tasks')
        # running 中的必然是 Restart
        for pending_task in self.config.pending_task:
            self.set_next_run(task=pending_task.command, target=delay_target)
        self.set_next_run(task='Restart', success=True, finish=True, server=True)
        self._set_runtime_outcome(status='server_update_delayed', wait_until=delay_target)
        return True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    config = Config('oas1')
    device = Device(config)
    task = ScriptTask(config, device)
    task.app_restart()
