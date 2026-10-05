# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import copy
import json
from pathlib import Path
from time import sleep

import difflib
from datetime import time, datetime, timedelta
from module.atom.image import RuleImage
from ppocronnx.predict_system import BoxedResult

from tasks.Component.config_base import Time
from tasks.DailyTrifles.page import (
    page_store_gift_room,
    page_friends_luck,
    page_guild_wish,
)

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import (
    page_main,
    page_storage,
    page_summon,
    page_guild,
    page_mall,
    page_friends,
    page_courtyard_affairs,
)
from tasks.GameUi.default_pages import random_click
from tasks.DailyTrifles.config import DailyTriflesConfig
from tasks.DailyTrifles.assets import DailyTriflesAssets
from tasks.Component.Summon.summon import Summon

from module.base.utils import save_image
from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer
from tasks.DailyTrifles.config import SummonType
import re
from typing import Any, Optional, List, Callable


class ScriptTask(GameUi, Summon, DailyTriflesAssets):

    def run(self):
        con = self.config.daily_trifles.trifles_config
        # 每日召唤
        if con.one_summon:
            self.run_one_summon()
        if con.courtyard_affairs:
            self.run_courtyard_affairs()
        if con.pickup_email:
            self.run_pickup_email()
        if self.config.daily_trifles.guild_donate.enable:
            self.run_guild_donate()
        # 吉闻
        if con.luck_msg:
            self.run_luck_msg()
        # 商店签到 or 购买寿司
        if con.store_sign or con.buy_sushi_count > 0:
            self.run_store()
        # 纳物库统计
        if con.storage_stats:
            self.run_storage_stats()
        self.config.save()
        self.plan_next_dt()
        raise TaskEnd('DailyTrifles')

    def run_one_summon(self):
        logger.hr('daily summon', 2)
        if self.config.daily_trifles.today_is_done('summon'):
            logger.info('Today is done, skip')
            return
        self.goto_page(page_summon)
        config = self.config.daily_trifles.trifles_config
        if config.summon_type == SummonType.default:
            self.summon_one(draw_mystery_pattern=config.draw_mystery_pattern)
            self.check_time()
        elif config.summon_type == SummonType.recall:
            self.summon_recall()
        self.back_summon_main()
        self.config.daily_trifles.done_record.summon_dt = datetime.now()

    def check_time(self):
        config = self.config.daily_trifles.trifles_config
        now = datetime.now()
        next_run = now + self.config.daily_trifles.scheduler.success_interval
        # 检查是否跨月（next_run的月份与当前月份不同）
        if next_run.month != now.month:
            # 跨月重置神秘图案触发状态
            if not config.draw_mystery_pattern:
                config.draw_mystery_pattern = True
                logger.info(f"reset draw_mystery_pattern to True, next_run: {next_run}")
        else:
            # 如果还是在同一月份，则没必要再绘制神秘图案
            config.draw_mystery_pattern = False
        self.config.save()

    def summon_recall(self):
        """
        确保在召唤界面,每日召唤一次
        召唤结束后回到 召唤主界面
        :return:
        """
        list = [self.O_SELECT_SM2, self.O_SELECT_SM3, self.O_SELECT_SM4]
        count = 0
        while True:
            count += 1

            for i in range(len(list)):
                sleep(1)
                self.goto_page(page_summon)
                self.appear_then_click(self.I_UI_BACK_RED, interval=1)
                x, y = list[i].coord()
                self.device.click(x, y)
                sleep(1)
                self.screenshot()
                if self.appear(self.I_RECALL_TICKET):
                    break
                logger.info("Select preset group RECALL")

            self.screenshot()
            if self.appear(self.I_RECALL_TICKET):
                break
            if count >= 3:
                self.config.notifier.push(
                    title='今忆召唤抽卡失败', content='每日任务,今忆召唤抽卡失败!!!'
                )
                return

        logger.info('Summon one RECALL')
        self.wait_until_appear(self.I_RECALL_TICKET)
        while True:
            ticket_info = self.O_RECALL_TICKET_AREA.ocr(self.device.image)
            # 处理 None 和空字符串
            if ticket_info is None or ticket_info == '':
                ticket_info = 0
            else:
                # 使用正则表达式提取字符串中的数字
                match = re.search(r'\d+', ticket_info)
                if match:
                    ticket_info = int(match.group())
                else:
                    logger.warning(
                        f'Invalid ticket_info value: {ticket_info}, expected a numeric string'
                    )
                    ticket_info = 0  # 将无效值设置为默认值 0
            if ticket_info <= 0:
                logger.warning('There is no any one RECALL ticket')
                return
            # 某些情况下滑动异常
            self.S_RANDOM_SWIPE_1.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_2.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_3.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_4.name = 'S_RANDOM_SWIPE'
            while 1:
                self.screenshot()
                if self.appear(self.I_RECALL_ONE_TICKET):
                    break
                if self.appear_then_click(self.I_RECALL_TICKET, interval=1):
                    continue

            # 画一张票
            sleep(1)
            while 1:
                self.screenshot()
                if self.appear(self.I_RECALL_SM_CONFIRM, interval=0.6):
                    self.ui_click_until_disappear(self.I_RECALL_SM_CONFIRM)
                    break
                if self.appear(self.I_SM_CONFIRM_2, interval=0.6):
                    self.ui_click_until_disappear(self.I_SM_CONFIRM_2)
                    break
                if self.appear(self.I_RECALL_ONE_TICKET, interval=1):
                    # 某些时候会点击到 “语言召唤”
                    if self.appear_then_click(self.I_UI_CANCEL, interval=0.8):
                        continue
                    self.summon()
                    continue
            logger.info('Summon one success')

    def run_guild_donate(self):
        logger.hr('guild donate', 2)
        if self.config.daily_trifles.today_is_done('guild_donate'):
            logger.info('Today is done, skip')
            return
        self.goto_page(page_guild_wish)
        timeout_timer = Timer(2).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_DT_GW_THANKS):
                self.ui_click(self.I_DT_GW_THANKS, self.I_DT_GW_THANKED, interval=0.8)
                timeout_timer.reset()
                continue
        self.appear_then_click(self.I_UI_BACK_RED)
        donate_datas: list = [
            (
                self.config.daily_trifles.guild_donate.guild_member_list_v,
                lambda: self.switch_select(
                    self.I_DT_GW_GUILD_MEMBER_SELECTED,
                    self.I_DT_GW_FRIEND_SELECTED,
                    self.I_DT_GW_SELECT_GUILD_MEMBER,
                ),
                self.config.daily_trifles.guild_donate.name_check,
            ),
            (
                self.config.daily_trifles.guild_donate.friend_list_v,
                lambda: self.switch_select(
                    self.I_DT_GW_FRIEND_SELECTED,
                    self.I_DT_GW_GUILD_MEMBER_SELECTED,
                    self.I_DT_GW_SELECT_FRIEND,
                ),
                self.config.daily_trifles.guild_donate.name_check,
            ),
        ]
        all_done = True
        for name_list, switch_func, name_check in donate_datas:
            # 分别执行两个名单，前一个名单失败也不能跳过后一个名单。
            donate_ret = self.donate(name_list, switch_func, name_check)
            all_done = all_done and donate_ret
        if self.config.daily_trifles.guild_donate.auto_get_rewards:
            self.guild_donate_get_reward()
        self.config.daily_trifles.done_record.guild_donate_finish = all_done
        self.goto_page(page_main)

    def guild_donate_get_reward(self):
        """领取捐赠碎片的奖励"""
        timeout_timer = Timer(3).start()
        has_reward = False
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_UI_BACK_RED, interval=0.6):
                break
            if self.appear(self.I_DT_GW_DONATE_RECORD_RED):
                self.ui_click(
                    self.I_DT_GW_DONATE_RECORD, self.I_UI_BACK_RED, interval=1.2
                )
                has_reward = True
                continue
        if not has_reward:
            logger.info('No reward can get, exit')
            return
        timeout_timer.reset()
        while not timeout_timer.reached():
            self.screenshot()
            self.ui_reward_appear_click()
            if self.appear_then_click(self.I_UI_CONFIRM, interval=0.6):
                continue
            if self.appear_then_click(
                self.I_DT_GW_DONATE_RECORD_THANKS, interval=1.5
            ):  # 受赠界面的一键感谢
                timeout_timer.reset()
                continue
            if self.appear(self.I_DT_GW_DONATE_RED, interval=2.5):  # 赠予界面的一键领取
                self.ui_click(self.I_DT_GW_GIVE, self.I_DT_GW_ONE_COLLECT)
                self.appear_then_click(self.I_DT_GW_ONE_COLLECT, interval=0.6)
                timeout_timer.reset()
                continue
        self.ui_click_until_disappear(self.I_UI_BACK_RED)

    def donate(
        self, name_list: List[str], switch_func: Callable, name_check: bool
    ) -> bool:
        """执行碎片捐赠流程

        :param name_list: 待捐赠碎皮的名称列表
        :param switch_func: 切换好友/阴阳寮/...的方法
        :param name_check: 是否使用ocr检查用户名
        :return: 是否全部捐赠成功 (出现检索名称后为空或者碎皮不足都是False, 仅全部捐成功才是True)
        """
        all_done = True
        for name in name_list:
            switch_func()
            self.swipe(self.S_DT_GW_OPEN_SEARCH, interval=1.2)  # 向下滑动拉出搜索框
            # 从按照交换搜索切换到按名称搜索
            self.switch_select(
                self.I_DT_GW_SEARCH_BY_NAME,
                self.I_DT_GW_SEARCH_BY_SWAP,
                self.I_DT_GW_SELECT_BY_NAME,
            )
            self.appear_then_click(self.I_DT_GW_CLEAR_SEARCH)  # 清除搜索框内容
            self.ui_click(
                self.C_DT_GW_INPUT_SEARCH, self.I_DT_GW_CONFIRM, interval=1.5
            )  # 点击搜索框
            self.click(self.C_DT_GW_CLICK_INPUT)  # 点击名称输入框
            # uiautomator2 通过 FastInputIME 传输 UTF-8 文本，并在必要时回退到 set_text
            logger.info(
                f'Inputting name using uiautomator2: {name}, waiting start and send'
            )
            self.device.u2.send_keys(name, clear=True)
            self.ui_click_until_disappear(
                self.I_DT_GW_CONFIRM, interval=1.5
            )  # 点击确定
            donate_btn = self.I_DT_GW_DONATE
            if name_check:  # 若有多个相同前缀名称, 则需要取出一样的或最相近的名称
                name_roi = self.find_target_name(name)
                if name_roi is None:
                    logger.warning(f'{name} check failed, maybe not wish or not find')
                    all_done = False
                    continue
                # 设置赠与按钮back与对应name同一行
                donate_btn.roi_back = [
                    name_roi[0] - 5,
                    name_roi[1] - 15,
                    850,
                    90,
                ]  # 设置赠与按钮back区域和对应name同一行
            self.I_DT_GW_FULL.roi_back = (
                donate_btn.roi_back
            )  # 设置已捐满标志back区域和赠与按钮同一行
            self.I_DT_GW_INSUFFICIENT.roi_back = (
                donate_btn.roi_back
            )  # 设置碎片不足标志back区域和赠与按钮同一行
            donate_ret = self.process_donate(donate_btn, name)
            all_done = all_done and donate_ret  # 有一次没成功则all_done永远False
        return all_done

    def process_donate(self, donate_btn: RuleImage, name: str) -> bool:
        """捐赠式神碎片
        TODO: 游戏有bug,搜索结束之后会突然神经展开全部寮友/好友,会有一瞬间识别到了好友,点击捐赠结果实际捐错人了

        :param name: 被捐方名称
        :param donate_btn: 赠与按钮
        :return: 捐赠是否成功(点击了捐赠/确定/识别到已满都认为成功)
        """
        timeout_timer = Timer(3).start()
        donated = False  # 判断是否已执行捐赠
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_DT_GW_SEARCH_EMPTY):
                logger.warning('Maybe not wish or not find, skip')
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(
                        title='好友搜索失败',
                        content=f'{name} 搜索失败, 没有搜索到对应用户, 无法捐赠',
                    )
                return False
            if not donated and self.appear_then_click(donate_btn, interval=2.5):
                timeout_timer.reset()
                # 点击后，等待所有弹窗消失（确认、奖励），然后重新定位
                post_click_timeout = Timer(3).start()
                while not post_click_timeout.reached():
                    self.screenshot()
                    # 处理确认弹窗
                    if self.appear(self.I_UI_CONFIRM, interval=0.6):
                        self.ui_get_reward(self.I_UI_CONFIRM, click_interval=1.5)
                        donated = True
                    # 如果没有弹窗了，退出子循环
                    if not self.appear(self.I_UI_REWARD) and not self.appear(
                        self.I_UI_REWARD
                    ):
                        break
                if donated:
                    # 处理了弹窗，视为捐赠成功
                    logger.info(f'Donate success for {name}!')
                    return True
                else:
                    # 子循环结束后，重新定位目标行（因为如果被搜索到的玩家有多个，被赠与方被赠送满了就会下沉到最后位置）
                    new_roi = self.find_target_name(name)
                    if new_roi is None:
                        logger.warning(f'{name} disappeared after donation, skip')
                        return False
                    # 更新三个按钮的 ROI
                    new_roi_back = [new_roi[0] - 5, new_roi[1] - 15, 850, 90]
                    donate_btn.roi_back = new_roi_back
                    self.I_DT_GW_FULL.roi_back = new_roi_back
                    self.I_DT_GW_INSUFFICIENT.roi_back = new_roi_back
                    logger.info(f"Updated ROI after donation attempt: {new_roi_back}")
                    continue

            if self.appear(self.I_DT_GW_INSUFFICIENT, interval=0.6):
                logger.warning('Not enough fragment to donate, skip')
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(
                        title='捐赠碎片不足',
                        content=f'捐给{name}的碎片不足, 请上线查看',
                    )
                return False
            if self.appear(self.I_DT_GW_FULL, interval=0.6):
                logger.info(f'Donate success!')
                donated = True
        return donated

    def find_target_name(self, name) -> List[int]:
        """寻找目标名称
        :param name: 名称
        :return: [x, y, w, h]
        """
        timeout_timer = Timer(3).start()
        name_roi: List[int] = None
        # TODO: 这里只找了第一页, 若相似名称过多后续需要添加翻页继续找功能
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_DT_GW_SEARCH_EMPTY):  # 空的直接退出
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(
                        title='好友搜索失败',
                        content=f'没有搜索到对应用户 {name}, 无法捐赠',
                    )
                return None
            text_results = self.O_DT_GW_NAME.detect_and_ocr(self.device.image)
            mx_similarity = 0.5
            for result in text_results:
                if result.ocr_text == name:
                    return self.extract_roi(result)  # 名称一模一样则直接返回
                similarity = difflib.SequenceMatcher(
                    None, result.ocr_text, name
                ).ratio()
                if similarity > mx_similarity:
                    mx_similarity = similarity
                    name_roi = self.extract_roi(result)
            if name_roi is None:
                continue
            return name_roi  # 找到了直接退出
        return name_roi

    def extract_roi(self, result: BoxedResult) -> list[int]:
        """从ocr结果提取对应的roi坐标"""
        x = self.O_DT_GW_NAME.roi[0] + result.box[0, 0]
        y = self.O_DT_GW_NAME.roi[1] + result.box[0, 1]
        w, h = result.box[1, 0] - result.box[0, 0], result.box[2, 1] - result.box[0, 1]
        return [x, y, w, h]

    def switch_select(self, target: RuleImage, other: RuleImage, select: RuleImage):
        """切换选中的元素"""
        while True:
            self.screenshot()
            if self.appear(target):
                break
            if self.appear_then_click(select, interval=0.6):
                continue
            if self.appear_then_click(other, interval=1.8):
                continue

    def run_luck_msg(self):
        logger.hr('luck msg', 2)
        if self.config.daily_trifles.today_is_done('luck_msg'):
            logger.info('Today is done, skip')
            return
        self.goto_page(page_friends_luck)
        logger.info('Start luck msg')
        check_timer = Timer(2)
        check_timer.start()
        while 1:
            self.screenshot()

            if self.appear_then_click(self.I_CLICK_BLESS, interval=1):
                continue
            if self.appear_then_click(self.I_ONE_CLICK_BLESS, interval=1):
                continue
            if self.ui_reward_appear_click():
                logger.info('Get reward of luck msg')
                break
            if check_timer.reached():
                logger.warning('There is no any luck msg')
                break

        self.goto_page(page_main)
        self.config.daily_trifles.done_record.luck_msg_dt = datetime.now()

    def run_store(self):
        if self.check_store_all_done():
            logger.info('Store all done, skip')
            return
        self.goto_page(page_mall, confirm_wait=3)
        if self.config.daily_trifles.trifles_config.store_sign:
            self.run_store_sign()
        if self.config.daily_trifles.trifles_config.buy_sushi_count > 0:
            self.run_buy_sushi()
        self.goto_page(page_main)

    def run_store_sign(self):
        logger.hr("store sign", 2)
        if self.config.daily_trifles.today_is_done("store_sign"):
            logger.info("Today is done, skip")
            return
        self.config.daily_trifles.done_record.store_sign_dt = datetime.now()
        self.goto_page(page_store_gift_room)
        self.screenshot()
        self.appear_then_click(self.I_GIFT_RECOMMEND, interval=1)
        logger.info("Enter store sign")
        sleep(1)  # 等个动画
        self.screenshot()
        if not self.appear(self.I_GIFT_SIGN):
            logger.warning("There is no gift sign")
            return

        if self.ui_get_reward(self.I_GIFT_SIGN, click_interval=2.5):
            logger.info('Get reward of gift sign')

        self.screenshot()
        if self.appear(self.I_GIFT_SIGN_GOT):
            self.click(random_click(ltrb=(True, False, False, False)), interval=1.5)
            return

    def run_buy_sushi(self):
        logger.hr('store sushi', 2)
        if self.config.daily_trifles.today_is_done('sushi'):
            logger.info('Today is done, skip')
            return
        # 进入Special
        while 1:
            from tasks.RichMan.assets import RichManAssets
            from tasks.LevelRush.assets import LevelRushAssets

            self.screenshot()
            if self.appear(RichManAssets.I_SIDE_CHECK_SPECIAL) and self.appear(
                self.I_SPECIAL_SUSHI
            ):
                break
            if self.appear(LevelRushAssets.I_SIDE_CHECK_ROOKIE_MALL):
                self.ui_click(
                    LevelRushAssets.I_ROOKIE_GOTO_SPECIAL,
                    RichManAssets.I_SIDE_CHECK_SPECIAL,
                )
                continue
            if self.appear_then_click(RichManAssets.I_MALL_SUNDRY, interval=1):
                continue

        def detect_buy_count(base_element) -> (int, int):
            # 返回count,price
            MAX_PRICE = 9999
            MAX_COUNT = 9999
            roi = copy.deepcopy(base_element.roi_front)
            roi[0] = roi[0] + roi[2]
            roi[1] = roi[1] + roi[3] - 45
            roi[2] = 75
            roi[3] = 45
            self.O_STORE_SUSHI_PRICE.roi = roi
            _price = self.O_STORE_SUSHI_PRICE.detect_text(self.device.image)
            # 保守策略，避免OCR错误购买
            try:
                _price = int(_price)
            except Exception as e:
                _price = MAX_PRICE

            if _price < 60:
                return 0, MAX_PRICE
            _count = (_price - 60) / 20
            return _count, _price

        roi = None
        # 购买体力
        while 1:
            self.screenshot()
            # count, price = detect_buy_count(roi)
            # if count >= self.config.model.daily_trifles.trifles_config.buy_sushi_count:
            #     break
            logger.info(
                f"购买次数为: {self.config.daily_trifles.trifles_config.buy_sushi_count} 次"
            )
            if self.appear(self.I_STORE_COST_TYPE_JADE):
                count, price = detect_buy_count(self.I_STORE_COST_TYPE_JADE)
                if count >= self.config.daily_trifles.trifles_config.buy_sushi_count:
                    break
                if self.ui_click_until_disappear(self.I_UI_CANCEL_SAMLL):
                    logger.info(f"Maybe jade not enough, stop")
                    break
                if self.ui_get_reward(self.I_STORE_COST_TYPE_JADE, click_interval=2.5):
                    logger.info(f"Buy Sushi With {price} Jade")
                    continue

            if self.appear(self.I_SPECIAL_SUSHI):
                # 此处确定当前购买体力所需勾玉数量的位置,用于后续识别
                count, price = detect_buy_count(self.I_SPECIAL_SUSHI)
                if count >= self.config.daily_trifles.trifles_config.buy_sushi_count:
                    logger.info(f"已经购买 {count} 次, 退出购买")
                    break
                self.ui_click(
                    self.I_SPECIAL_SUSHI, stop=self.I_STORE_COST_TYPE_JADE, interval=2
                )
                continue
        self.config.daily_trifles.done_record.sushi_dt = datetime.now()

    def run_courtyard_affairs(self):
        """庭院事务"""
        logger.hr('courtyard affairs', 2)
        self.goto_page(page_main)
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_ENTER_COURTYARD_AFFAIRS, interval=1.2):
                self.goto_page(page_courtyard_affairs)
                timeout_timer.reset()
                break
        if timeout_timer.reached():
            logger.info('Not have courtyard affairs, exit')
            return
        while True:
            self.screenshot()
            if self.appear(self.I_CHECK_IN_DAILY, interval=0.5):
                break
            if self.appear_then_click(self.I_ENTER_DAILY, interval=1):
                continue
        self.appear_then_click(self.I_ONE_COMPLETE, interval=1)
        self.goto_page(page_main)
        self.config.daily_trifles.done_record.courtyard_affairs_dt = datetime.now()

    def run_pickup_email(self):
        """领取邮件"""
        logger.hr('pick up email', 2)
        self.goto_page(page_main)
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if (
                self.appear_then_click(self.I_DT_HARVEST_MAIL_COPY2, interval=1.2)
                or self.appear_then_click(self.I_HARVEST_MAIL, interval=1.2)
                or self.appear_then_click(self.I_HARVEST_MAIL_COPY, interval=1.2)
            ):
                continue
            if self.appear_then_click(self.I_HARVEST_MAIL_CONFIRM, interval=1):
                continue
            if self.appear_then_click(self.I_HARVEST_MAIL_ALL, interval=2):
                timeout_timer.reset()
                continue
            if self.appear_then_click(self.I_READ_ALL_MAIL, interval=3):
                continue
        self.goto_page(page_main)
        self.config.daily_trifles.done_record.pickup_email_dt = datetime.now()

    def plan_next_dt(self):
        # 定时领体力（每天 12-14、20-22 时内各有 20 体力）
        now = datetime.now()
        # 如果时间在00:00-12:00之间则设定时间为当日 12 时
        if now.time() < time(12, 0):
            self.custom_next_run(
                task='DailyTrifles', custom_time=Time(12, 0), time_delta=0
            )
        # 如果时间在12:00-20:00之间则设定时间为当日 20 时
        elif time(12, 0) <= now.time() < time(20, 0):
            self.custom_next_run(
                task='DailyTrifles', custom_time=Time(20, 0), time_delta=0
            )
        # 如果时间在20:00-23:59之间则设定时间为次日 12 时
        else:
            self.custom_next_run(
                task='DailyTrifles', custom_time=Time(12, 0), time_delta=1
            )

    def check_store_all_done(self) -> bool:
        """判断商店任务是否都做完了, 做完了则不再进入商店"""
        if (
            self.config.daily_trifles.trifles_config.store_sign
            and not self.config.daily_trifles.today_is_done('store_sign')
        ):
            return False
        if (
            self.config.daily_trifles.trifles_config.buy_sushi_count > 0
            and not self.config.daily_trifles.today_is_done('sushi')
        ):
            return False
        return True

    # 标题栏三条规则是 Single 模式，值可能带 万/亿/小数点，需要按白名单清洗。
    # 数字是叠画在图标右下角上的，OCR 会把图标边缘一起读进来，
    # 实测出现过 `_2856` / `L2` / `L40` / `LD265` 这类前缀噪声，一律按无效字符丢弃。
    STORAGE_VALUE_NOISE = re.compile(r'[^0-9.万亿]')
    # 清洗后再取第一个合法数值，丢掉 `..`、`万` 开头之类的残渣
    STORAGE_VALUE_PATTERN = re.compile(r'\d+(?:\.\d+)?[万亿]?')

    @classmethod
    def clean_storage_value(cls, value):
        """清洗纳物库 OCR 结果。

        - 仓库计数用的是 `Digit` 模式，`ocr()` 直接返回 int，本身已经是纯数字，原样保留；
        - 标题栏金币/体力/勾玉用的是 `Single` 模式，返回 str，只保留 0-9、小数点、万、亿，
          再取第一个合法数值：`_2856` -> `2856`，`L40` -> `40`，`9.0万` -> `9.0万`；
          一个数字都没有时视为识别失败，返回空串。
        """
        if isinstance(value, (int, float)):
            return value
        if not value:
            return ''
        cleaned = cls.STORAGE_VALUE_NOISE.sub('', str(value))
        matched = cls.STORAGE_VALUE_PATTERN.search(cleaned)
        return matched.group(0) if matched else ''

    def run_storage_stats(self) -> dict:
        """纳物库统计

        进入纳物库后截图存档到 ./log/storage_stats/{实例名}/{日期}/，
        再用 stats/image.json 的模板定位各资源图标，以图标「右下角」为锚点算出计数区做 OCR，
        结果经 clean_storage_value() 清洗后与截图同名前缀落盘为 json。
        """
        logger.hr('storage stats', 2)
        self.goto_page(page_storage)
        self.ui_click_until_disappear(self.I_SWITCH_TO_RESOURCE, interval=0.5)
        self.screenshot()

        # 1. 截图存档：./log/storage_stats/{实例名}/{日期}/{时间戳}.png
        # 同一天的所有运行落在同一个日期文件夹里；日期与文件名取同一次 now，避免跨零点错位。
        instance = re.sub(r'[^\w.-]', '_', self.config.config_name)
        now = datetime.now()
        folder = Path('./log/storage_stats') / instance / now.strftime('%Y-%m-%d')
        folder.mkdir(parents=True, exist_ok=True)
        timestamp = now.strftime('%Y-%m-%d_%H-%M-%S')
        png_file = folder / f'{timestamp}.png'
        save_image(self.device.image, str(png_file))
        logger.info(f'纳物库截图已保存至 {png_file}')

        # 2. 标题栏上的三个资源：金币 / 体力 / 勾玉
        stats = {
            '金币': self.clean_storage_value(self.O_GOLD_COUNT.ocr(self.device.image)),
            '体力': self.clean_storage_value(self.O_SUSHI_COUNT.ocr(self.device.image)),
            '勾玉': self.clean_storage_value(self.O_JADE_COUNT.ocr(self.device.image)),
        }

        # 3. 仓库内的资源：先用图片规则定位图标，再按位置算出计数区做 OCR
        # 每项第三个元素是计数用的 OCR 规则（Digit 模式，返回 int）：
        # 默认用短的 LOW（60x24，够放 4 位数），位数可能更多的资源用长的 HIGH（80x24）。
        low = DailyTriflesAssets.O_COMMON_COUNT_LOW
        high = DailyTriflesAssets.O_COMMON_COUNT_HIGH
        items = (
            ('蓝票', DailyTriflesAssets.I_BLUE_TICKET, low),
            ('金蛇皮', DailyTriflesAssets.I_GOLD_SKIN, high),
            ('逢魔皮', DailyTriflesAssets.I_DEMON_SKIN, high),
            ('现世符咒', DailyTriflesAssets.I_PRESENT_WORLD_TICKET, low),
            ('海蛇皮', DailyTriflesAssets.I_SEA_SKIN, high),
            ('御札', DailyTriflesAssets.I_RETURN_SOUL, low),
        )

        # 一次性预取所有模板的匹配结果，减少 RPC 次数
        self.prepare_appear_cache([rule for _, rule, _ in items])
        # 只向上扩、底边不动，避免切到大字号（如两位数）的下缘。
        count_top_expand = 2
        for name, rule, ocr_rule in items:
            if not self.appear(rule):
                # 页面上确实没有这个资源（例如现世符咒已用完）→ 记为 0，不再漏掉这个键；
                logger.info(f'纳物库中未找到资源 {name}，记为 0')
                stats[name] = '0'
                continue

            x, y, w, h = rule.roi_front
            declared = (list(ocr_rule.roi), list(ocr_rule.area))
            roi_w, roi_h = declared[0][2], declared[0][3]
            count_roi = [
                x + w - roi_w,
                y + h - count_top_expand,
                roi_w,
                roi_h + count_top_expand,
            ]
            ocr_rule.roi = count_roi
            ocr_rule.area = count_roi
            try:
                stats[name] = self.clean_storage_value(ocr_rule.ocr(self.device.image))
            finally:
                ocr_rule.roi, ocr_rule.area = declared

        logger.info(f'纳物库统计结果: {stats}')

        # 4. 统计结果与截图同名前缀落盘
        json_file = png_file.with_suffix('.json')
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        logger.info(f'纳物库统计结果已保存至 {json_file}')

        self.goto_page(page_main)
        return stats


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas2')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run_guild_donate()
