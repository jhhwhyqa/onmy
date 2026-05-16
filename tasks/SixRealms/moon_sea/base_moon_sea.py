import re
from cached_property import cached_property
from module.base.timer import Timer

from module.logger import logger
import tasks.SixRealms.moon_sea.page as pages
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle, BattleContext, BattleAction
from tasks.GameUi.navigator import GameUi
from tasks.base_task import BaseTask
from tasks.SixRealms.assets import SixRealmsAssets


class BaseMoonSea(GameUi, GeneralBattle, BaseTask, SixRealmsAssets):
    coin_num = 0  # 钱币数量
    cnt_skill101 = 0  # 柔风等级

    def before_run(self):
        pages.page_battle = self.navigator.resolve_page(pages.page_battle)
        pages.page_battle.recognizer = pages.any_of(self.I_BOSS_SKIP, pages.page_battle.recognizer)
        pages.page_battle_result = self.navigator.resolve_page(pages.page_battle_result)
        pages.page_battle_result.recognizer = pages.any_of(self.I_BOSS_BATTLE_AGAIN, self.I_BOSS_BATTLE_GIVEUP,
                                                           self.I_SELECT_3, self.I_SKILL_REFRESH, self.I_UI_CONFIRM_SAMLL,
                                                           pages.page_battle_result.recognizer)
        pages.page_reward = self.navigator.resolve_page(pages.page_reward)
        pages.page_reward.recognizer = pages.any_of(self.I_COIN, self.I_SR_DOUBLE_REWARD_USE, self.I_BOSS_GET_EXP,
                                                    self.I_BOSS_SHARE, self.I_BOSS_SHUTU, self.I_MS_SKILL_UNLOCK,
                                                    pages.page_reward.recognizer)

    def _handle_in_battle(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        if self.appear_then_click(self.I_BOSS_SKIP, interval=0.8):
            return BattleAction.CONTINUE
        return super()._handle_in_battle(context, config)

    def _handle_result(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        context.reward_no_battle_ts = None
        # 打输了, 直接放弃
        if self.appear(self.I_BOSS_BATTLE_GIVEUP):
            context.is_win = False
            self.click(self.I_BOSS_BATTLE_GIVEUP, interval=0.8)
            return BattleAction.CONTINUE
        # 放弃之后的2次弹窗确认
        if self.appear(self.I_UI_CONFIRM_SAMLL):
            self.click(self.I_UI_CONFIRM_SAMLL, interval=0.8)
            return BattleAction.CONTINUE
        # 选择一个技能
        if self.appear(self.I_SELECT_3, interval=1.5) and self.appear(self.I_SKILL_REFRESH):
            context.is_win = True
            self.coin_num = self.O_COIN_NUM.ocr(self.device.image)
            logger.info(f'Current coin: {self.coin_num}')
            select = self._select_skill()
            self.appear_then_click(self.selects_button[select], interval=1)
        return BattleAction.CONTINUE

    def _handle_reward(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        context.reward_no_battle_ts = None
        if self.appear(self.I_BOSS_SHUTU):  # 极表示boss战赢了
            context.is_win = True
        if context.is_win and self.appear_then_click(self.I_SR_DOUBLE_REWARD_USE, interval=1.5):
            return BattleAction.CONTINUE
        if not context.is_win and self.appear_then_click(self.I_SR_DOUBLE_REWARD_CANCEL, interval=1.5):
            return BattleAction.CONTINUE
        if self.appear(self.I_COIN, interval=2):
            x, y, width, height = self.I_COIN.roi_front
            self.O_EXTRA_COIN_NUM.roi = [x + 25, y + 47, width - 5, height - 23]
            extra_coin = self.O_EXTRA_COIN_NUM.ocr_digit(self.device.image)
            extra_coin = int(extra_coin) if extra_coin != "" else 0
            self.coin_num += extra_coin
            logger.info(f'Current coin: {self.coin_num}')
        self.click(pages.random_click(), interval=1.2)
        self.device.click_record_clear()
        return BattleAction.CONTINUE

    @cached_property
    def selects_button(self):
        return [
            self.I_SELECT_0,
            self.I_SELECT_1,
            self.I_SELECT_2,
            self.I_SELECT_3,
        ]

    def enter_battle(self) -> bool:
        """进入战斗"""
        if self.appear(self.I_BATTLE_TEAM_UNLOCK):
            self.ui_click(self.I_BATTLE_TEAM_UNLOCK, self.I_BATTLE_TEAM_LOCK, interval=0.8)
        if self.appear(self.I_BOSS_TEAM_UNLOCK):
            self.ui_click(self.I_BOSS_TEAM_UNLOCK, self.I_BOSS_TEAM_LOCK, interval=0.8)
        self.device.stuck_record_clear()
        timeout_timer = Timer(5).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.get_current_page() in (pages.page_battle_prepare, pages.page_battle, pages.page_battle_result):
                return True
            self.appear_then_click(self.I_BATTLE_FIRE, interval=0.8)
        return False

    def _select_skill(self) -> int:
        select = 3  # 从0开始计数
        button = None
        if self.appear(self.I_SKILL101):  # 柔风
            self.cnt_skill101 += 1
            logger.info(f'Skill 101 level: {self.cnt_skill101}')
            button = self.I_SKILL101
        elif self.appear(self.I_SKILL105):  # 洞察之力
            button = self.I_SKILL105
        if button is not None:
            x, y = button.front_center()
            if x < 360:
                select = 0
            elif 360 <= x < 640:
                select = 1
            elif 640 <= x < 960:
                select = 2
        logger.info(f'Select {select}')
        return select

    def refresh_store(self) -> bool:
        logger.info('Refresh store')
        text = self.O_STORE_REFRESH_TIME.ocr(self.device.image)
        matches = re.search(f"剩\d+次", text)
        if not matches:
            logger.warning('Refresh time not match, exit')
            return False
        refresh_time = int(matches.group()[1])
        logger.info(f'Refresh time: {refresh_time}')
        if refresh_time <= 0:
            logger.warning('Refresh time is 0')
            return False
        if not self.appear_then_click(self.I_STORE_REFRESH):
            return False
        self.wait_animate_stable(self.C_STORE_ANIMATE_KEEP, timeout=1.5)
        logger.info('Refresh store done')
        return True

    def open_shop(self) -> bool:
        """手动打开商店"""
        timeout_timer = Timer(5).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_MS_LAND_SHOP):
                return True
            if self.appear_then_click(self.I_UI_CONFIRM):
                continue
            if self.appear_then_click(self.I_M_STORE_ACTIVITY, interval=1.5):
                continue
        self.appear_then_click(self.I_UI_CANCEL)
        return False
