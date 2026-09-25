# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
"""限时活动：LBS鬼王。

"""
import re
import time
from datetime import datetime, timedelta

from cached_property import cached_property

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralInvite.general_invite import GeneralInvite
from tasks.Component.GeneralRoom.general_room import GeneralRoom
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.LBS.assets import LBSAssets
from tasks.LBS.config import LBS

# 点挑战后等待进入战斗的超时（秒）
ENTER_BATTLE_TIMEOUT = 30


class ScriptTask(GeneralBattle, GameUi, GeneralRoom, GeneralInvite, SwitchSoul, LBSAssets):

    success_count = 0
    limit_count = 0
    limit_time: timedelta = None

    @cached_property
    def conf(self) -> LBS:
        return self.config.model.lbs

    def run(self):
        self.success_count = 0
        self.limit_count = self.conf.lbs_config.limit_count
        limit_time = self.conf.lbs_config.limit_time
        self.limit_time = timedelta(
            hours=limit_time.hour,
            minutes=limit_time.minute,
            seconds=limit_time.second,
        )

        self.switch_soul()
        # 本地化：原为 self.ui_goto_page(page_main)，本地框架是 goto_page
        self.goto_page(page_main)
        self.enter_lbs()

        success = self.run_rounds()

        self.exit_room()
        self.exit_team()
        self.set_next_run(task='LBS', success=success, finish=True)
        raise TaskEnd('LBS')

    # ------------------------------------------------------------------ 主体循环

    def run_rounds(self) -> bool:
        """一轮：点「组队」→「创建」→ 点挑战开战 → 打一场；打完再点「组队」重复。"""
        while 1:
            self.screenshot()
            if self.success_count >= self.limit_count:
                logger.info('LBS 成功次数已达上限')
                return True
            if datetime.now() - self.start_time >= self.limit_time:
                logger.info('LBS 时间已达上限')
                return True
            # 点「组队」前先查剩余次数：为 0 就没有可打的了，直接结束
            if not self.check_remain_count():
                return True
            # 每轮都要重新点「组队 → 创建」；建房后右下角会出现挑战
            self.ui_click(self.I_TEAM_UP, self.I_TEAM_CREATE)
            self.ui_click(self.I_TEAM_CREATE, self.I_CHALLENGE)
            if not self.click_challenge():
                logger.warning('LBS 点了挑战但未进入战斗，结束本次运行')
                return False
            # 准备 / 战斗 / 结算（确认奖励）交给框架；打完回到「组队」可见的界面即本场结束
            if self.run_general_battle(
                config=self.conf.battle_conf, exit_matcher=self.I_TEAM_UP
            ):
                self.success_count += 1
            logger.info(f'成功次数: {self.success_count}/{self.limit_count}')

    def check_remain_count(self) -> bool:
        """点「组队」前查一下剩余挑战次数；为 0 返回 False（该结束任务了）。

        `O_REMAIN_COUNT` 的 roi 需要按实机自行配置（`res/ocr.json` 里现在是占位值）。
        **读不到数字时按"还有次数"处理**，避免 roi 没配好就误判成 0 直接结束。
        """
        self.screenshot()
        text = self.O_REMAIN_COUNT.ocr(self.device.image)
        numbers = re.findall(r'\d+', str(text))
        if not numbers:
            logger.warning(f'LBS 读不到剩余次数（OCR={text!r}），按还有次数继续')
            return True
        count = int(numbers[0])
        logger.info(f'LBS 剩余挑战次数: {count}')
        if count <= 0:
            logger.info('LBS 剩余挑战次数为 0，结束本次运行')
            return False
        return True

    def click_challenge(self) -> bool:
        """点挑战直到进入战斗（挑战按钮消失即视为已进入）。

        用 **LBS 自己的挑战模板 `I_CHALLENGE`**，不能用框架的 `I_FIRE`：`I_FIRE` 的搜索窗口
        与模板同尺寸（roi 1179,602,81x74，只在该点精确比对、不滑动搜索），而 LBS 房间里的
        挑战在 1196,617、尺寸 54x45，永远匹配不上。另外加了超时，避免点不动时无限空转。
        """
        deadline = Timer(ENTER_BATTLE_TIMEOUT).start()
        while not deadline.reached():
            self.screenshot()
            if not self.appear(self.I_CHALLENGE):
                return True
            self.appear_then_click(self.I_CHALLENGE, interval=1.5)
            time.sleep(0.3)
        logger.warning('LBS 点了挑战但未进入战斗')
        return False

    # ------------------------------------------------------------------ 导航

    def enter_lbs(self):
        """刷新列表找到入口，直到「组队」按钮出现。

        入口已经在场时 `ui_click` 会直接返回、不会真的去点刷新。
        """
        self.ui_click(self.I_REFRESH, self.I_ACTIVITY_ENTRY)
        self.ui_click(self.I_ACTIVITY_ENTRY, self.I_TEAM_UP)

    # ------------------------------------------------------------------ 御魂

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


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
