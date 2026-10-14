# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep
from datetime import time, datetime, timedelta

from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer

from module.atom.image import RuleImage
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_delegation
from tasks.Delegation.config import DelegationConfig
from tasks.Delegation.assets import DelegationAssets


class ScriptTask(GameUi, DelegationAssets):

    def run(self):
        self.goto_page(page_delegation)
        self.check_reward()
        con: DelegationConfig = self.config.delegation.delegation_config
        if con.miyoshino_painting:
            self.delegate_one('画')
        if con.bird_feather:
            self.delegate_one('鸟羽')
        if con.find_earring:
            self.delegate_one('寻找耳环')
        if con.cat_boss:
            self.delegate_one('猫老大')
        if con.miyoshino:
            self.delegate_one('接送')
        if con.strange_trace:
            self.delegate_one('痕迹')


        self.set_next_run(task='Delegation', success=True, finish=True)
        raise TaskEnd

    def delegate_one(self, name: str, entry: RuleImage = None) -> bool:
        """
        委派一个任务
        :param name: 委派名称（用 OCR 在委派列表里找它）
        :param entry: 可选的 image 规则；给了就直接用它点列表里的条目（名称 OCR 不稳时用）
        :return: 找到并点开了该委派返回 True
        """
        logger.hr('Delegation one', 2)
        self.screenshot()
        if entry is None:
            self.O_D_NAME.keyword = name
            self.screenshot()
            if not self.ocr_appear(self.O_D_NAME):
                logger.warning(f'Delegation: {name} not found')
                return False
        elif not self.appear(entry):
            logger.warning(f'Delegation: {name} entry not found by image')
            return False
        while 1:
            self.screenshot()
            if self.appear(self.I_D_START):
                break
            # 如果出现’召回‘ ’返回‘ 说明这个是现在委派中
            # 需要退出
            if self.appear(self.I_D_BACK):
                logger.warning(f'Delegation: {name} is in delegation')
                self.ui_click_until_disappear(self.I_D_BACK)
                self.wait_until_appear(self.I_REWARDS_MIN)
                return False
            if self.appear_then_click(self.I_D_SKIP, interval=0.8):
                continue
            if self.appear_then_click(self.I_D_CONFIRM, interval=0.8):
                continue
            if entry is None and self.ocr_appear_click(self.O_D_NAME, interval=1):
                continue
            if entry is not None and self.appear_then_click(entry, interval=1):
                continue
        # 进入委派  fefe e  fe
        logger.info(f'Enter Delegation: {name}')
        # 一键选择式神：点一下把式神位填满（不再逐个点位选择）
        if not self.wait_until_appear_then_click(self.I_D_QUICK_SELECT, wait_time=10):
            logger.warning(f'Delegation: quick select not found for {name}')
            return False
        # 委派开始
        logger.info(f'Delegation: {name} start')
        while 1:
            self.screenshot()
            if not self.appear(self.I_D_START):
                break
            if self.appear_then_click(self.I_D_START, interval=1.8):
                continue
        # self.ui_click_until_disappear(self.I_D_START)
        return True

    def check_reward(self):
        check_timer = Timer(3)
        check_timer.start()
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_REWARDS_GET, interval=1):
                check_timer.reset()
                continue
            if self.appear_then_click(self.I_REWARDS_CHAT, interval=1):
                check_timer.reset()
                continue
            if self.appear_then_click(self.I_CHAT_1, interval=1):
                check_timer.reset()
                continue
            if self.appear_then_click(self.I_CHAT_2, interval=1):
                check_timer.reset()
                continue
            if self.appear_then_click(self.I_REWARDS_DONE, interval=1):
                check_timer.reset()
                continue
            if self.appear_then_click(self.I_REWARDS_FALSE, interval=1):
                check_timer.reset()
                continue


            if not self.appear(self.I_REWARDS_MIN):
                continue
            if check_timer.reached():
                break
            if self.ocr_appear_click(self.O_D_DONE, interval=1):
                check_timer.reset()
                continue


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    from memory_profiler import profile
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    # t.delegate_one('弥助的画')
    t.run()




