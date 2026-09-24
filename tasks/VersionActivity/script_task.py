# This Python file uses the following encoding: utf-8
"""限时活动：版本活动（月华流光）。

按本地 `BaseAct`（`tasks/ActivityShikigami/base_act.py`）的状态机写法实现：
用异常做流程控制（次数上限 / 时间上限 / 资源不足），主体在 `run_moonlight` 里
「定位入口 -> 进挑战页 -> 读资源 -> 点挑战 -> 处理弹窗 -> 打一场」循环。
开跑前若 `switch_soul_config` 勾选，会先回式神录按配置切换御魂（复用
`tasks/Component/SwitchSoul`）。

与上游 tomoe1-1/OnmyojiAutoScript @ d52612c1 的 `tasks/Moonlight` 的差异：
那条流程依赖上游的 action_type 活动框架（`action_limit` / `prepare_next_action` /
`record_action` / `finish_activity_task` 等），本地没有，所以按本地架构重写；
识别素材与判定条件（资源阈值 6、奖励上限弹窗文案、战斗配置覆盖）与上游一致。
"""
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

# 每次挑战消耗的挑战资源，低于该值不再挑战（与上游一致）
CHALLENGE_RESOURCE_COST = 6
# 点击挑战后等待进入战斗的超时（秒）
ENTER_BATTLE_TIMEOUT = 30


class LimitCountOut(Exception):
    """挑战次数已用完。"""


class LimitTimeOut(Exception):
    """运行时间已达上限。"""


class ResourceNotEnough(Exception):
    """挑战资源不足，提前结束。"""


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, VersionActivityAssets):
    """月华流光：按次数与时间上限循环挑战。"""

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
                'Moonlight challenge count reached: %s/%s',
                self.count,
                self.conf.version_activity_config.challenge_limit,
            )
            raise LimitCountOut
        if (
            datetime.now() - self.start_time
            >= self.conf.version_activity_config.limit_time_v
        ):
            logger.info('Moonlight time limit reached')
            raise LimitTimeOut

    def run(self):
        self.count = 0
        self.switch_soul()
        try:
            self.run_moonlight()
        except (LimitCountOut, LimitTimeOut, ResourceNotEnough) as e:
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

    def run_moonlight(self):
        logger.hr('Start activity: 月华流光', 1)
        self.goto_page(page_main)
        if not pages.find_moonlight_entry(self):
            raise GamePageUnknownError('Cannot find Moonlight entry')
        self.goto_page(pages.page_moon_battle)
        first_battle = True
        while True:
            self.update_status()
            # 上一场打完会回到挑战页；若被挤到别处（结算/奖励页）由导航器带回
            self.goto_page(pages.page_moon_battle)
            if not self.enter_moonlight_battle():
                raise ResourceNotEnough
            self.count += 1
            if self.conf.version_activity_config.random_sleep:
                random_sleep(probability=0.2)
            self.run_general_battle(
                config=self.build_battle_conf(first_battle),
                battle_key='version_activity_moonlight',
                exit_matcher=self.I_MOON_BATTLE,
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
        """按上游做法覆盖战斗配置：只在第一场用预设出战、不锁阵容、不连续战斗。"""
        source = self.conf.battle_conf
        return source.model_copy(
            update={
                'preset_enable': source.preset_enable and first_battle,
                'lock_team_enable': False,
                'continuous_battle': False,
                'max_continuous': 0,
            }
        )

    def enter_moonlight_battle(self) -> bool:
        """在挑战页点一次挑战并等待进入战斗。

        只在确认处于挑战页时点击；资源不足（连续两次读数都低于消耗）或出现
        未知确认弹窗时安全退出，返回 False 让上层结束本次运行。
        """
        self.screenshot()
        if not self.appear(self.I_MOON_BATTLE):
            raise GameStuckError('Moonlight challenge page is not visible')
        resource = self.O_MOON_RESOURCE.ocr_digit(self.device.image)
        if resource < CHALLENGE_RESOURCE_COST:
            # 资源是实时刷新/有延迟的，再读一次确认
            time.sleep(0.3)
            self.screenshot()
            if not self.appear(self.I_MOON_BATTLE):
                raise GameStuckError(
                    'Moonlight page changed while checking challenge resource'
                )
            resource = self.O_MOON_RESOURCE.ocr_digit(self.device.image)
            if resource < CHALLENGE_RESOURCE_COST:
                logger.info(
                    'Moonlight challenge resource %s below %s on two reads; stop challenges',
                    resource,
                    CHALLENGE_RESOURCE_COST,
                )
                return False
        # 不做盲点击：按钮没出现就报错
        if not self.appear_then_click(self.I_MOON_CHALLENGE, interval=1):
            raise GameStuckError(
                'Moonlight challenge button is not visible or click was blocked'
            )
        deadline = Timer(ENTER_BATTLE_TIMEOUT).start()
        reward_cap_confirmed = False
        while not deadline.reached():
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if self.appear(self.I_UI_CONFIRM) or self.appear(self.I_UI_CONFIRM_SAMLL):
                notice = ''.join(
                    result.ocr_text
                    for result in self.O_MOON_REWARD_NOTICE.detect_and_ocr(
                        self.device.image
                    )
                ).replace(' ', '')
                if '奖励已达获取上限' in notice and '继续挑战' in notice:
                    # 「奖励已达获取上限，是否继续挑战」——只有这一种弹窗才确认
                    if not reward_cap_confirmed:
                        if not (
                            self.appear_then_click(self.I_UI_CONFIRM, interval=1)
                            or self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1)
                        ):
                            raise GameStuckError(
                                'Moonlight reward-cap confirmation could not be clicked'
                            )
                        reward_cap_confirmed = True
                    time.sleep(0.3)
                    continue
                # 其它未知确认框一律取消，不盲点确认
                logger.warning(
                    'Moonlight challenge blocked by unknown confirmation dialog; stop safely'
                )
                if self.appear_then_click(
                    self.I_UI_CANCEL, interval=1
                ) or self.appear_then_click(self.I_UI_CANCEL_SAMLL, interval=1):
                    return False
                raise GameStuckError(
                    'Moonlight confirmation dialog could not be cancelled'
                )
            time.sleep(0.3)
        raise GameStuckError('Moonlight did not enter battle after challenge')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
