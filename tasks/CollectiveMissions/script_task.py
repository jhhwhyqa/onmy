# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
from time import sleep

import random
import re
from cached_property import cached_property
from enum import Enum
from datetime import timedelta
from module.atom.image import RuleImage

from module.exception import TaskEnd, RequestHumanTakeover
from module.logger import logger
from module.base.timer import Timer
from module.atom.ocr import RuleOcr
from tasks.CollectiveMissions.config import MC
from tasks.CollectiveMissions.page import page_collective_missions

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_guild
from tasks.CollectiveMissions.assets import CollectiveMissionsAssets


class ScriptTask(GameUi, CollectiveMissionsAssets):
    """阴阳寮集体任务"""

    current_mission: MC = None

    def run(self):
        self.goto_page(page_collective_missions)
        logger.info('Start to detect missions')
        self.get_task_reward()
        if self.is_finish():
            self.goto_page(page_main)
            self.set_next_run(task='CollectiveMissions', success=True)
            raise TaskEnd
        self.select_and_update_cur_mission(self.config.collective_missions.missions_config.missions_select)
        if self.current_mission is None:
            self.goto_page(page_main)
            self.set_next_run(task='CollectiveMissions', success=False)
            raise TaskEnd
        match self.current_mission:
            case MC.FEED:
                self._feed()  # 喂 N 卡
            case MC.AW1 | MC.AW2 | MC.AW3 | MC.GR1 | MC.GR2 | MC.GR3:
                self._donate()  # 捐材料
            case MC.SO1 | MC.SO2:
                self._soul()  # 捐御魂
        self.goto_page(page_main)
        self.set_next_run(task='CollectiveMissions', success=True)
        raise TaskEnd

    def select_and_update_cur_mission(self, mission: MC) -> bool:
        :return: 成功选择返回True
        """
        # 兜底: 万一 OCR 一直认不出目标(例如 魂/灵 这类混字), 别把任务永远卡在这里
        deadline = time.time() + 10 * 60
        switch_cnt = 0
        miss_switch = 0
        while True:
            if time.time() >= deadline:
                logger.warning(f'Cannot find target mission {mission.value} in 10min, exit')
                return False
            self.screenshot()
            # 识别当前任务
            mission_text = self.O_CM_2.ocr(self.device.image)
            try:
                detect_mission = MC(mission_text)
                logger.info(f"Current: {detect_mission.value}, target: {mission.value}")
                if detect_mission == mission:
                    self.current_mission = detect_mission
                    logger.info(f"Success select mission[{mission_text}]")
                    return True
            except ValueError:
                logger.warning(f'Unknown {mission_text}, skip')
            logger.info(f"Try switch to next mission [{switch_cnt}]")
            if self.appear_then_click(self.I_CM_SWITCH, interval=0.6):
                sleep(random.uniform(0.6, 1.2))
                switch_cnt += 1
                miss_switch = 0
                self.device.click_record_clear()
            else:
                # 找不到刷新按钮说明当前不在任务列表页, 别在这里空转到卡死检测
                miss_switch += 1
                if miss_switch >= 5:
                    logger.warning('Cannot find switch button, stop select')
                    return False
                sleep(0.5)

    def click_until_appear(self, click, stop, timeout: float = 15, interval: float = 1.5) -> bool:
        timeout_timer = Timer(timeout).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(stop):
                return True
            if isinstance(click, RuleImage):
                self.appear_then_click(click, interval=interval)
            else:
                self.click(click, interval=interval)
        logger.warning(f'{stop.name} not appear in {timeout}s, stop clicking')
        return False

    def _donate(self):
        """捐材料"""
        if not self.click_until_appear(self.C_CM_1, self.I_CM_PRESENT, interval=1.5):
            return
        logger.info('Start to donate')
        # 判断哪一个的材料最多
        self.screenshot()
        max_index = 0
        max_number = 0
        for i, ocr in enumerate([self.O_CM_1_MATTER, self.O_CM_2_MATTER,
                                 self.O_CM_3_MATTER, self.O_CM_4_MATTER]):
            curr, remain, total = ocr.ocr(self.device.image)
            if total > max_number:
                max_number = total
                max_index = i
        if max_number <= 30:
            logger.info('The number of all matter is less than 30')
            logger.info('Please check your game resolution')
            raise RequestHumanTakeover
        match_swipe = {
            0: self.S_CM_MATTER_1,
            1: self.S_CM_MATTER_2,
            2: self.S_CM_MATTER_3,
            3: self.S_CM_MATTER_4,
        }
        # 滑动到最多的材料
        random_click = [self.I_CM_ADD_1, self.I_CM_ADD_2, self.I_CM_ADD_3, self.I_CM_ADD_4]
        window_control = self.config.script.device.control_method == 'window_message'
        swipe_count = 0
        click_count = 0
        while 1:
            self.screenshot()
            if self.appear(self.I_CM_MATTER):
                break
            if not window_control and self.swipe(match_swipe[max_index], interval=2.5):
                swipe_count += 1
                time.sleep(1.5)
                continue
            # 为什么使用window_message无法滑动
            if window_control and click_count > 30:
                logger.info('Swipe to the most matter failed')
                logger.info('Please check your game resolution')
                break
            if window_control and self.click(random.choice(random_click), interval=0.7):
                click_count += 1
                continue
            if not window_control and swipe_count >= 5:
                logger.info('Swipe to the most matter failed')
                logger.info('Please check your game resolution')
                raise RequestHumanTakeover
        logger.info('Swipe to the most matter')
        self.get_reward_and_close(self.I_CM_PRESENT)
        logger.info('Donate finished')
        return True

    def _soul(self):
        """提交御魂"""
        if not self.click_until_appear(self.C_CM_1, self.I_SL_SUBMIT, interval=1):
            return
        while 1:
            self.screenshot()
            number_text = self.O_SL_NUMBER.ocr(self.device.image)
            submit_number = int(re.findall(r'\d+', number_text)[-1])
            if submit_number > 0:
                break
            if self.ocr_appear(self.O_SL_LEVEL):
                # 如果没有识别到这个，那就说明没有御魂可以提交了，要退出
                logger.warning('No soul can be submit')
                self.click_until_appear(self.I_UI_BACK_RED, self.I_CM_RECORDS, interval=1)
                return False
            if self.click(self.L_SL_LONG, interval=2.5):
                time.sleep(1)
                continue
        logger.info('Start to collect soul rewards')
        self.get_reward_and_close(self.I_SL_SUBMIT)
        logger.info('Finish to collect soul rewards')
        return True

    def _feed(self):
        """提交N卡"""
        logger.info('Start to feed N')
        if not self.click_until_appear(self.C_CM_1, self.I_FEED_HEAP, interval=1):
            return
        logger.info('Submit to feed N')
        click_list = random.sample([self.L_FEED_CLICK_1, self.L_FEED_CLICK_2, self.L_FEED_CLICK_3, self.L_FEED_CLICK_4], 2)
        while 1:
            self.screenshot()
            if self.appear(self.I_FEED_SUBMIT):
                break
            for click in click_list:
                self.click(click)
        logger.info('Start to collect feed N rewards')
        self.get_reward_and_close(self.I_FEED_SUBMIT)
        logger.info('Finish to collect feed N rewards')
        return True

    def is_finish(self):
        """判断寮三十是否已经捐满"""
        self.screenshot()
        current, remain, total = self.O_CM_NUMBER.ocr(self.device.image)
        if current == total == 30:
            logger.info('Today\'s missions have been completed')
            return True
        return False

    def get_task_reward(self):
        """获取其他已完成的任务奖励"""
        timeout_timer = Timer(3).start()
        process_reward = False
        while not timeout_timer.reached():
            self.maybe_screenshot()
            if not self.appear(self.I_CM_GET_REWARD):
                break
            process_reward = True
            logger.info('Discover the tasks that have been completed')
            self.get_reward_and_close(self.I_CM_GET_REWARD)
            timeout_timer.reset()
        if process_reward:
            logger.info('Get task reward finished')
        else:
            logger.info('No task reward')

    def get_reward_and_close(self,  target: RuleImage):
        # 捐赠可能有双倍的，需要领两次
        reward_number = 0
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if reward_number >= 2:
                break
            if self.ui_reward_appear_click(False):
                reward_number += 1
                continue
            if self.appear_then_click(target, interval=1):
                continue
        self.ui_reward_appear_click(True)  # 兜底再尝试领取一次


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()

