from datetime import datetime, timedelta

from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.SwitchAccount.switch_account import SwitchAccount
from tasks.AccountSwitch.assets import AccountSwitchAssets
from tasks.AccountSwitch.config import AccountSwitch
from tasks.GameUi.game_ui import GameUi


class ScriptTask(GameUi, AccountSwitchAssets):
    conf: AccountSwitch = None

    def run(self):
        self.conf = self.config.account_switch
        cfg = self.conf.account_switch_config
        accounts = [a for a in self.conf.account_list if a.is_valid()]
        if not accounts:
            logger.warning('AccountSwitch: 没有配置有效账号，退出')
            raise TaskEnd('AccountSwitch')

        # 指针不能超出真实可切的账号
        total = min(len(accounts), cfg.switch_account_count)
        today = datetime.now().strftime('%Y-%m-%d')
        current_index = self._get_current_index(total)
        target_index = self._next_pending_index(accounts, total, current_index, today)
        if target_index is None:
            # 当天所有账号都已切过，等明天再从第一个号开始
            logger.info('AccountSwitch: 今日 %d 个号已全部切过，明天再来' % total)
            self._set_current_index(0)
            self._schedule_next_day()
            raise TaskEnd('AccountSwitch')

        target = accounts[target_index]
        logger.hr(
            'AccountSwitch: 切换到 %s-%s（第 %d/%d 个号）'
            % (target.character, target.svr, target_index + 1, total),
            2,
        )

        switched = SwitchAccount(self.config, self.device, target).switchAccount()
        # 无论成功失败都记入当天缓存：失败时指针同样推进，避免 30 秒后重试同一个号
        self._mark_switched(target, today)
        self._set_current_index((target_index + 1) % total)

        if not switched:
            logger.warning(
                'AccountSwitch: 切换到 %s-%s 失败，本轮结束'
                % (target.character, target.svr),
            )
            raise TaskEnd('AccountSwitch')

        logger.info('AccountSwitch: %s-%s 登录成功' % (target.character, target.svr))

        if cfg.trigger_all_enabled_tasks:
            self._trigger_all_enabled_tasks()

        # 当天每个号都切过 = 一轮结束，等 1 天再来
        if self._all_switched(accounts, total, today):
            logger.info('AccountSwitch: 今日 %d 个号已全部切完，下次运行 1 天后' % total)
            self._set_current_index(0)
            self._schedule_next_day()
        else:
            self.set_next_run(task='AccountSwitch', success=True, finish=True)

        raise TaskEnd('AccountSwitch')

    @staticmethod
    def _next_pending_index(accounts, total: int, start: int, today: str):
        """从指针位置开始找当天还没切过的账号，全部切过时返回 None。"""
        for offset in range(total):
            index = (start + offset) % total
            if accounts[index].switch_date != today:
                return index
        return None

    @staticmethod
    def _all_switched(accounts, total: int, today: str) -> bool:
        return all(accounts[index].switch_date == today for index in range(total))

    def _mark_switched(self, account, today: str) -> None:
        """把账号记入当天缓存，重启或重复运行时不再切回它。"""
        account.switch_date = today
        self.config.save()
        logger.info(
            'AccountSwitch: 记录 %s-%s 今日已切号' % (account.character, account.svr)
        )

    def _schedule_next_day(self) -> None:
        tomorrow = datetime.now().replace(microsecond=0) + timedelta(days=1)
        self.set_next_run(task='AccountSwitch', server=False, target=tomorrow)

    def _get_current_index(self, count: int) -> int:
        """读取指针, 越界归零"""
        cfg = self.conf.account_switch_config
        index = getattr(cfg, 'current_index', 0)
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = 0
        if index < 0 or index >= count:
            index = 0
        return index

    def _set_current_index(self, index: int) -> None:
        """保存指针"""
        cfg = self.conf.account_switch_config
        cfg.current_index = index
        self.config.save()
        logger.info('AccountSwitch: 指针推进到 %d' % index)

    def _trigger_all_enabled_tasks(self) -> None:
        """把所有已启用任务的运行时间置为现在"""
        now = datetime.now().replace(microsecond=0)
        triggered = []
        for key, value in self.config.model.model_dump().items():
            if not isinstance(value, dict):
                continue
            scheduler = value.get('scheduler')
            if not scheduler or not scheduler.get('enable'):
                continue
            # 跳过自己和 restart
            if key in ('account_switch', 'restart'):
                continue
            if self.config.model.deep_set(
                self.config.model, keys=f'{key}.scheduler.next_run', value=now
            ):
                triggered.append(key)
        if triggered:
            self.config.save()
            logger.info(
                'AccountSwitch: 已触发 %d 个任务立即执行 -> %s'
                % (len(triggered), ', '.join(triggered)),
            )
        else:
            logger.info('AccountSwitch: 没有其它已启用任务可触发')

    def save_config(self):
        self.config.save()


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas4')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
