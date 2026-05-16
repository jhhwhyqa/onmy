import time

import random
import re
from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.page_definition import Page
from tasks.SixRealms.moon_sea.base_moon_sea import BaseMoonSea

import tasks.SixRealms.moon_sea.page as pages
from typing import Callable


class MoonSea(BaseMoonSea):
    """月之海"""
    
    @property
    def ms_page_handle_dict(self) -> dict[Page, Callable]:
        return {
            pages.page_moon_sea: self.run_on_ms,
            pages.page_ms_prepare: self.run_on_ms_prepare,
            pages.page_ms_main: self.run_on_ms_main,
            pages.page_ms_shop_land: self.run_on_ms_store,
            pages.page_ms_mistery_land: self.run_on_ms_mistery,
            pages.page_ms_chaos_land: self.run_on_ms_chaos,
            pages.page_ms_star_land: self.run_on_ms_star,
            pages.page_ms_battle_land: self.run_on_ms_battle,
            pages.page_ms_challenge: self.run_on_ms_challenge,
            pages.page_ms_exit: lambda : self.click(random_click(ltrb=(True, False, False, False)), interval=1.2),
            pages.page_ms_prepare_exit: lambda : self.goto_page(pages.page_ms_prepare),
            pages.page_ms_open_store: lambda : self.goto_page(pages.page_ms_main),
            pages.page_battle_prepare: self.run_on_ms_challenge,
            pages.page_battle: self.run_on_ms_challenge,
            pages.page_battle_result: self.run_on_ms_challenge,
            pages.page_reward: lambda : self.click(random_click(), interval=1.2),
        }

    def run_moon_sea(self):
        self.before_run()
        logger.hr('Moon Sea', 1)
        while True:
            self.screenshot()
            current_page = self.get_current_page()
            if current_page is None:
                time.sleep(0.5)
                continue
            handle = self.ms_page_handle_dict.get(current_page, None)
            if handle is None:
                self.goto_page(pages.page_moon_sea)
                continue
            try:
                handle()
            except TaskEnd:
                break

    def run_on_ms(self):
        """月之海界面"""
        if self.appear_then_click(self.I_MCONINUE, interval=1):
            return
        if self.appear_then_click(self.I_MSTART, interval=1):
            return

    def run_on_ms_prepare(self):
        """进入月之海主界面前的准备界面"""
        if self.appear_then_click(self.I_MSTART_CONFIRM, interval=1.5) or \
                self.appear_then_click(self.I_MSTART_CONFIRM2, interval=1.5):
            return
        if self.appear_then_click(self.I_MFIRST_SKILL, interval=1.5):
            self.cnt_skill101 = 1
            return

    def run_on_ms_main(self):
        """月之海主界面 执行策略选岛屿"""
        if self.appear(self.I_BOSS_FIRE_PREPARE) and self.enter_battle():
            logger.info('Start boss battle')
            self.run_general_battle(battle_key='boss', exit_matcher=pages.page_moon_sea)
            raise TaskEnd
        remain_turns_txt = self.O_REMAIN_TURNS.ocr(self.device.image)
        match = re.search(r'\d{1,2}', remain_turns_txt)
        remain_turns = 99
        if not set(remain_turns_txt).isdisjoint(set('回合')) and match:
            remain_turns = int(match.group())
        # 优先级：商店 > 神秘 > 混沌 > 星之屿 > 战斗
        lands = [
            self.I_MS_LAND_SHOP,
            self.I_MS_LAND_MYSTERY,
            self.I_MS_LAND_CHAOS,
            self.I_MS_LAND_STAR,
            self.I_MS_LAND_FIRE,
        ]
        self.prepare_appear_cache(lands)
        appeared_lands = [land for land in lands if self.appear(land)]
        if len(appeared_lands) == 0:
            logger.info('No land recognized, retry')
            return
        appeared_shop = self.appear(self.I_MS_LAND_SHOP)
        # 剩余回合数<=1&商店未出现&技能未满&金币足够打开商店和买柔风, 则开启商店
        if remain_turns <= 1 and not appeared_shop and self.cnt_skill101 < 5 and self.coin_num >= 600:
            self.open_shop()
            return
        # 出现商店&岛屿数量>2&金币不够买柔风&剩余回合数>1, 则不选择商店, 先攒金币
        if appeared_shop and len(appeared_lands) >= 2 and self.coin_num < 300 and remain_turns > 1:
            logger.info('Money is not enough, choose other land')
            appeared_lands.remove(self.I_MS_LAND_SHOP)
        target_land = appeared_lands[0]  # 取第一个岛屿
        self.appear_then_click(target_land, interval=1.5)

    def run_on_ms_challenge(self):
        """月之海挑战界面"""
        if self.enter_battle():
            self.run_general_battle(battle_key="normal", exit_matcher=pages.page_ms_main)

    def run_on_ms_store(self):
        """宁息商店"""
        logger.hr('shop land')
        if self.cnt_skill101 >= 5:
            logger.info('Skill level is enough, skip shopping')
            self.goto_page(pages.page_ms_main)
            return 
        buy_interval_timer = Timer(1.5)
        while True:
            self.screenshot()
            if self.appear_then_click(self.I_UI_CONFIRM, interval=1):
                continue
            if not buy_interval_timer.reached():
                continue
            buy_interval_timer.reset()
            self.coin_num = self.O_COIN_NUM.ocr(self.device.image)
            logger.info(f'Current coin: {self.coin_num}')
            # 钱够买柔风, 则买
            if self.appear(self.I_STORE_SKILL_101) and self.coin_num >= 300:
                x, y = self.I_STORE_SKILL_101.front_center()
                x -= random.randint(35, 60)
                y += random.randint(-self.I_STORE_SKILL_101.roi_front[3] // 2, self.I_STORE_SKILL_101.roi_front[3] // 2)
                self.device.click(x=x, y=y, control_name='STORE_SKILL_101')
                continue
            # 钱够刷新+买柔风, 则刷新
            if self.coin_num >= 400 and self.refresh_store():
                continue
            logger.info('Not have enough coin to refresh and buy')
            break
        logger.info('Finish purchase skill 101')
        self.goto_page(pages.page_ms_main)

    def run_on_ms_mistery(self):
        """神秘之屿 转换/仿造"""
        logger.hr('mistery land')
        if not self.appear(self.I_MISTERY_IMITATE):
            logger.info('Do not transfer skill')
            self.goto_page(pages.page_ms_main)
            return
        logger.info('Imitate skill')
        if self.cnt_skill101 >= 5:
            logger.info('Skill level is enough, skip imitating')
            self.goto_page(pages.page_ms_main)
            return
        if not self.appear_then_click(self.I_MISTERY_IMITATE_SKILL_101):
            self.goto_page(pages.page_ms_main)
            return
        max_imitate = random.randint(2, 3)
        imitated = False
        while True:
            self.screenshot()
            if self.get_current_page() == pages.page_ms_main:
                break
            if max_imitate <= 0:
                logger.warning("Skill level may be maxed out, skip")
                break
            if self.appear(self.I_MISTERY_IMITATE_SUCCESS):
                self.click(pages.random_click(), interval=1.5)
                imitated = True
                continue
            if self.appear_then_click(self.I_UI_CONFIRM, interval=1.5):
                imitated = True
                continue
            if self.appear_then_click(self.I_MISTERY_IMITATE, interval=2.5):
                max_imitate -= 1
        self.cnt_skill101 += 1 if imitated else 0
        logger.info(f'Skill 101 level: {self.cnt_skill101}')
        logger.info('Finish Imitate')
        self.goto_page(pages.page_ms_main)

    def run_on_ms_chaos(self):
        """混沌之屿 宝箱/精英"""
        logger.hr('chaos land')
        is_box: bool = self.appear(self.I_CHAOS_BOX_EXIT)
        if is_box:
            logger.info('Do not get box')
            self.goto_page(pages.page_ms_main)
            return
        self.ui_click(self.C_NPC_FIRE_CENTER, self.I_BATTLE_FIRE, interval=0.8)
        if self.enter_battle():
            logger.info('Start elite battle')
            self.run_general_battle(battle_key="elite", exit_matcher=pages.page_ms_main)

    def run_on_ms_star(self):
        """星之屿 红蛋/星之子"""
        logger.hr('star land')
        self.ui_click(self.C_NPC_FIRE_LEFT, self.I_BATTLE_FIRE, interval=0.8)
        if self.enter_battle():
            logger.info('Start star red egg battle')
            self.run_general_battle(battle_key="normal", exit_matcher=pages.page_ms_main)

    def run_on_ms_battle(self):
        """鏖战之屿 普通怪"""
        logger.hr('fire land')
        self.ui_click(self.C_NPC_FIRE_RIGHT, self.I_BATTLE_FIRE, interval=0.8)
        if self.enter_battle():
            logger.info('Start normal battle')
            self.run_general_battle(battle_key="normal", exit_matcher=pages.page_ms_main)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常1')
    d = Device(c)
    t = MoonSea(c, d)
    t.screenshot()

    t.run_moon_sea()
