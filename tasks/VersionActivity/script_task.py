# This Python file uses the following encoding: utf-8
"""限时活动：版本活动（锦绣南行 · 学艺切磋）。

按本地 `BaseAct`（`tasks/ActivityShikigami/base_act.py`）的状态机写法实现：
用异常做流程控制（次数上限 / 时间上限），主体在 `run_version_activity` 里
「定位入口 -> 进挑战页 -> 读剩余次数 -> 点挑战 -> 打一场」循环。
开跑前若 `switch_soul_config` 勾选，会先回式神录按配置切换御魂（复用
`tasks/Component/SwitchSoul`）。

剩余次数读取挑战页右下角的「剩x/30次」；x 为 0 或达到
`challenge_limit` 时结束本次运行。
"""
import re
import time
from datetime import datetime

from cached_property import cached_property

from module.base.protect import random_sleep
from module.base.timer import Timer
from module.exception import GamePageUnknownError, GameStuckError, TaskEnd
from module.logger import logger

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.VersionActivity.assets import VersionActivityAssets
from tasks.VersionActivity.config import VersionActivity
import tasks.VersionActivity.page as pages

# 挑战页剩余次数的上限
MAX_REMAIN_TIMES = 30
# 点击挑战后等待进入战斗的超时（秒）
ENTER_BATTLE_TIMEOUT = 30


class LimitCountOut(Exception):
    """挑战次数已用完。"""


class LimitTimeOut(Exception):
    """运行时间已达上限。"""


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, VersionActivityAssets):
    """版本活动（锦绣南行 · 学艺切磋）：按剩余次数与时间上限循环挑战。"""

    conf: VersionActivity = None
    count: int = 0

    @cached_property
    def conf(self) -> VersionActivity:
        return self.config.model.version_activity

    # ------------------------------------------------------------------ 流程控制

    def update_status(self):
        """每次挑战前检查次数与时间上限，超出则抛异常结束。"""
        if self.count >= self.conf.version_activity_config.challenge_limit:
            logger.info(
                'VersionActivity challenge count reached: %s/%s',
                self.count,
                self.conf.version_activity_config.challenge_limit,
            )
            raise LimitCountOut
        if (
            datetime.now() - self.start_time
            >= self.conf.version_activity_config.limit_time_v
        ):
            logger.info('VersionActivity time limit reached')
            raise LimitTimeOut

    def run(self):
        self.count = 0
        self.switch_soul()
        try:
            self.run_version_activity()
        except (LimitCountOut, LimitTimeOut) as e:
            logger.info(f'VersionActivity finished this run: {type(e).__name__}')
        self.finish_activity_task()

    def switch_soul(self):
        """按配置在式神录切换御魂。

        组号队伍号与按名称两种方式各自独立判断（与其它任务一致），都不勾选则不做任何操作。
        """
        cfg = self.conf.switch_soul_config
        if cfg.enable:
            logger.hr('Switch soul by group team', 2)
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(cfg.switch_group_team)
        if cfg.enable_switch_by_name:
            logger.hr('Switch soul by name', 2)
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(cfg.group_name, cfg.team_name)

    def run_version_activity(self):
        logger.hr('Start activity: 锦绣南行', 1)
        self.goto_page(page_main)
        if not pages.find_version_entry(self):
            raise GamePageUnknownError('Cannot find VersionActivity entry')
        self.goto_page(pages.page_version_battle)
        first_battle = True
        while True:
            self.update_status()
            # 上一场打完会回到挑战页；若被挤到别处（结算/奖励页）由导航器带回
            self.goto_page(pages.page_version_battle)
            self.enter_version_battle()
            self.count += 1
            if self.conf.version_activity_config.random_sleep:
                random_sleep(probability=0.2)
            self.run_general_battle(
                config=self.build_battle_conf(first_battle),
                battle_key='version_activity',
                exit_matcher=self.I_VERSION_BATTLE,
            )
            first_battle = False

    def finish_activity_task(self):
        """回到庭院，按配置整理御魂，并安排下次运行。"""
        self.goto_page(page_main)
        if self.conf.version_activity_config.active_souls_clean:
            self.set_next_run(
                task='SoulsTidy', success=False, finish=False, target=datetime.now()
            )
        self.set_next_run(task='VersionActivity', success=True, finish=True)
        raise TaskEnd('VersionActivity')

    # ------------------------------------------------------------------ 战斗

    def build_battle_conf(self, first_battle: bool) -> GeneralBattleConfig:
        """只在第一场用预设出战、不锁阵容、不连续战斗。"""
        source = self.conf.battle_conf
        return source.model_copy(
            update={
                'preset_enable': source.preset_enable and first_battle,
                'lock_team_enable': False,
                'continuous_battle': False,
                'max_continuous': 0,
            }
        )

    def _read_remaining_times_once(self) -> int | None:
        """读取一次剩余次数；区域不存在/文字为空时返回 None。"""
        self.screenshot()
        text = ''.join(
            str(self.O_VERSION_REMAIN_TIMES.ocr_single(self.device.image) or '').split()
        )
        if not text:
            return None
        match = re.search(r'(\d+)\s*[/／]\s*30', text)
        if match is None:
            raise GameStuckError(
                f'VersionActivity remaining times unreadable: [{text}]'
            )
        value = int(match.group(1))
        if not 0 <= value <= MAX_REMAIN_TIMES:
            raise GameStuckError(
                f'VersionActivity remaining times out of range: {value}'
            )
        return value

    def read_remaining_times(self) -> int:
        """读取剩余次数；连续两次读不到才视为 0。"""
        value = self._read_remaining_times_once()
        if value is not None:
            logger.info(
                f'VersionActivity remaining times: {value}/{MAX_REMAIN_TIMES}'
            )
            return value
        # 页面刷新/动画瞬间可能暂时读不到，再确认一次
        time.sleep(0.3)
        value = self._read_remaining_times_once()
        if value is None:
            logger.info(
                'VersionActivity remaining times area is absent; treat as 0'
            )
            return 0
        logger.info(f'VersionActivity remaining times: {value}/{MAX_REMAIN_TIMES}')
        return value

    def enter_version_battle(self):
        """在挑战页确认还有次数后点击挑战，并等待进入战斗。"""
        self.screenshot()
        if not self.appear(self.I_VERSION_BATTLE):
            raise GameStuckError('VersionActivity challenge page is not visible')
        remaining = self.read_remaining_times()
        if remaining == 0:
            logger.info('VersionActivity remaining challenge times is 0')
            raise LimitCountOut
        if not self.appear_then_click(self.I_VERSION_CHALLENGE, interval=1):
            raise GameStuckError(
                'VersionActivity challenge button is not visible or click was blocked'
            )
        deadline = Timer(ENTER_BATTLE_TIMEOUT).start()
        while not deadline.reached():
            self.screenshot()
            if self.is_in_battle(False):
                return
            time.sleep(0.3)
        raise GameStuckError('VersionActivity did not enter battle after challenge')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
