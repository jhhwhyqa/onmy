# This Python file uses the following encoding: utf-8
# @brief    Ryou Dokan Toppa (阴阳竂道馆突破功能)
# @author   AzurTian
# @note     draft version without full test
import re
from datetime import datetime
from time import sleep

from module.base.timer import Timer
from module.logger import logger
from tasks.Component.DokanCore.task_base import (
    DokanFinishedError,
    DokanNotStartedError,
    DokanTaskBase,
    position_offset,
)
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import BattleAction, BattleBehaviorScope, BattleContext
from tasks.Dokan.assets import DokanAssets
from tasks.Dokan.config import Dokan
import tasks.Dokan.page as pages


class ScriptTask(DokanTaskBase, DokanAssets):
    attack_priority_selected: bool = False
    switch_member_soul_done: bool = False
    switch_owner_soul_done: bool = False
    dokan_owner_battle: bool = False  # 馆主战标识
    first_master_killed: bool = False  # 一阵是否被击败
    found_dokan_cnt: int = 0  # 已经寻找道馆的次数

    CONFIG_KEY = 'dokan'
    TASK_NAME = 'Dokan'
    NEXT_RUN_SERVER = False
    pages = pages
    conf: Dokan = None

    def _get_battle_behavior_scopes(self, config: GeneralBattleConfig, battle_key: str) -> dict[str, BattleBehaviorScope]:
        scopes = super()._get_battle_behavior_scopes(config, battle_key)
        if battle_key == 'dokan_owner':
            scopes['green'] = BattleBehaviorScope.ROUND
        return scopes

    def _handle_in_battle(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        count = self.conf.attack_count_config.attack_dokan_master_count()
        if self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_FIRST) or self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND):
            self.dokan_owner_battle = True  # 防止直接在战斗界面识别, 因此在这继续更新一次馆主战标识
        if self.dokan_owner_battle:
            if count <= 0:  # 不让打直接退
                return BattleAction.QUICK_EXIT
            if self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND):
                self.first_master_killed = True  # 别到二阵则说明一阵被击败了
                if count <= 1:  # 2阵但只允许打一次
                    return BattleAction.QUICK_EXIT
        return super()._handle_in_battle(context, config)

    def select_dokan_target(self) -> None:
        try_start_dokan = self.conf.dokan_config.try_start_dokan
        if not try_start_dokan or self.found_dokan_cnt > 0:  # 未设置开启道馆/已经找过道馆但是没进去则退出
            raise DokanNotStartedError
        if self.update_remain_attack_count() <= 0:  # 可挑战次数<=0, 当作道馆成功完成
            raise DokanFinishedError
        if datetime.now().weekday() == 0:  # NOTE 只在周一尝试建立道馆
            self.creat_dokan()
        if not self.find_dokan(self.conf.dokan_config.find_dokan_score):
            raise DokanNotStartedError
        # 寻找到道馆后等一会页面刷新
        self.wait_until_appear(self.I_RYOU_DOKAN_CENTER_TOP, True, 5)

    def run_owner_battle_from_battle_page(self) -> None:
        self.first_master_killed = self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND)
        self.run_general_battle(self.conf.dokan_owner_battle_conf, battle_key='dokan_owner')

    def handle_owner_state(self) -> bool:
        """馆主战：按配置打馆主；不再打馆主且有权限时放弃突破。"""
        if self.appear(self.I_DOKAN_BOSS_WAITING) or not self.appear(self.I_RYOU_DOKAN_START_CHALLENGE):
            return False
        count = self.conf.attack_count_config.attack_dokan_master_count()
        if (count - (1 if self.first_master_killed else 0)) > 0:
            logger.info("Start owner battle")
            self.switch_soul_in_dokan('owner')
            if self.click_until_in_battle():
                self.run_general_battle(self.conf.dokan_owner_battle_conf, battle_key='dokan_owner')
        # 有权限且当前道馆突破不再打馆主, 直接放弃突破
        elif self.conf.dokan_config.try_start_dokan:
            self.abandoned_toppa()
        return True

    def handle_cd(self) -> None:
        self.start_cheering()

    def handle_vote_or_finish(self) -> None:
        if self.appear_then_click(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED, interval=2):  # 放弃突破
            return
        if self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY, interval=2):  # 投票
            # 每天打一次的直接选择保留赏金; 打两次的第一次选择继续挑战
            if self.conf.attack_count_config.daily_attack_count == 2:
                if self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN):
                    self.ui_click_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN)
            else:
                if self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY):
                    logger.info("Dokan challenge failed: vote for keep the awards")
                    self.ui_click_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY)
            return
        if self.appear(self.I_RYOU_DOKAN_TODAY_ATTACK_COUNT) or self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE):
            logger.info("Dokan challenge finished, exit Dokan")
            self.update_remain_attack_count()  # 更新配置
            raise DokanFinishedError

    def prepare_member_soul(self) -> None:
        self.switch_soul_in_dokan('member')

    def should_retry_today(self) -> bool:
        return (self.conf.attack_count_config.remain_attack_count == 1
                and self.conf.attack_count_config.daily_attack_count == 2)

    def find_dokan(self, score=4.6):
        """
        寻找符合条件的道馆进行挑战。

        参数:
        score (float): 赏金与人数比值的阈值，默认为4.6。

        返回:
        bool: 是否找到了符合条件的道馆并进行挑战。
        """
        self.found_dokan_cnt += 1
        # 刷新按钮点击次数
        num_fresh = 0
        # 备份一些重要的ROI区域，以便在循环中恢复
        backup = {'i_point_bounty': self.I_RIGHTPAD_POINT_BOUNTY.roi_back,
                  'i_point_people_num': self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back}

        def restore_roi():
            self.I_RIGHTPAD_POINT_BOUNTY.roi_back = backup['i_point_bounty']
            self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back = backup['i_point_people_num']

        def find_challengeable(ignore_score=False):
            """
            查找当前列表状态(一般为4个)中符合条件的道馆, 并点击使其显示挑战按钮。

            :param ignore_score: True 时选择当前列表中系数最低的那个
            :return: 是否找到并点击了挑战按钮
            """
            restore_roi()
            self.screenshot()
            bounty_list = self.find_all_element(self.I_RIGHTPAD_POINT_BOUNTY, (0, 0, 0, 50))
            logger.info(f'find elements list:{bounty_list}')
            # 默认最小分数
            min_score = 10
            idx_selected = -1
            for idx, item in enumerate(bounty_list):
                self.device.click_record_clear()
                logger.info(f"------start no.{idx} =={item}-----------")
                # 点击使挑战按钮消失的区域, 点击可能点到其他寮, 因此多点几次
                self.screenshot()
                while self.appear(self.I_CENTER_CHALLENGE):
                    self.click(self.C_DOKAN_CANCEL_SELECT_DOKAN, interval=1.5)
                    self.wait_animate_stable(self.C_DOKAN_CANCEL_SELECT_DOKAN_CHECK_ANIMATE, interval=0.5, timeout=1.5)

                # 获取赏金金额
                self.O_DOKAN_RIGHTPAD_BOUNTY.roi = position_offset(item, (0, 0, 100, 0))
                bounty = self.O_DOKAN_RIGHTPAD_BOUNTY.ocr(self.device.image)
                tmp = re.search(r'(\d+)', bounty)
                if not tmp:
                    logger.warning(f"can't find bounty,item = {item},ocr bounty={bounty}")
                    continue
                bounty = float(tmp.group())
                # 扩大搜索区域,防止找不到
                self.I_RIGHTPAD_POINT_BOUNTY.roi_back = position_offset(item, (-10, -10, 20, 20))
                # Note: 道馆不可挑战时(被别的寮打了),8秒后跳过
                if not self.ui_click_until_appear_or_timeout(self.I_RIGHTPAD_POINT_BOUNTY, self.I_CENTER_CHALLENGE,
                                                             interval=1.5, timeout=8):
                    logger.info(f"can't find challenge button,idx={idx} item={item}")
                    continue
                # 获取防守人数
                self.screenshot()
                if not self.appear(self.I_CENTER_POINT_PEOPLE_NUMBER):
                    logger.warning(f"can't find point people number image, item={item}")
                    continue
                self.O_DOKAN_CENTER_PEOPLE_NUMBER.roi = position_offset(
                    self.I_CENTER_POINT_PEOPLE_NUMBER.roi_front, (0, 0, 0, 30))
                p_num = self.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text(self.device.image)
                tmp = re.search(r"(\d+)", p_num)
                if not tmp:
                    logger.warning(f"can't find people number in ocr result,item={item}, p_num={p_num}")
                    continue
                p_num = float(tmp.group())
                logger.info(f"bounty:{bounty},people_num:{p_num},score:{bounty / p_num}")
                item_score = bounty / p_num
                if item_score < min_score:
                    min_score = item_score
                    idx_selected = idx
                # 大于系数 或者 系数过小(文字识别错误导致)
                if item_score > score or item_score < 1.5:
                    logger.info("click to making challenge disappear")
                    continue
                if p_num < self.conf.dokan_config.min_people_num:
                    logger.info("people num too small")
                    continue
                if bounty < self.conf.dokan_config.min_bounty:
                    logger.info("bounty too small")
                    continue
                # 馆主不是修习等级的
                if not self.appear(self.I_CENTER_GUANZHU_XIUXI):
                    continue
                logger.info(f"find_dokan: bounty:{bounty},people_num:{p_num},score:{bounty / p_num}")
                return True
            # 在所有列表中都没有符合的, 且忽略系数限制, 那么选择最低分数的那个
            if ignore_score:
                x, y, w, h = bounty_list[idx_selected]
                while 1:
                    self.screenshot()
                    if self.appear(self.I_CENTER_CHALLENGE):
                        return True
                    self.device.click(x, y)
                    sleep(0.5)
            return False

        while num_fresh < self.conf.dokan_config.find_dokan_refresh_count:
            for i in range(3):
                sleep(3)
                if find_challengeable():
                    logger.info("find challengeable dokan")
                    self.ui_click(self.I_CENTER_CHALLENGE, self.I_CHALLENGE_ENSURE, interval=1)
                    self.ui_click_until_disappear(self.I_CHALLENGE_ENSURE, interval=1)
                    # 更新可挑战次数
                    self.conf.attack_count_config.del_attack_count(1, self.config.save)
                    restore_roi()
                    return True
                # 滑动道馆列表
                self.swipe(self.S_DOKAN_LIST_UP)
            restore_roi()
            logger.info("=========refresh dokan list=========")
            self.ui_click(self.C_DOKAN_REFRESH, self.I_REFRESH_ENSURE, interval=1)
            self.ui_click_until_disappear(self.I_REFRESH_ENSURE, interval=1)
            logger.info("Refresh Done")
            num_fresh += 1
        # 刷新次数用完,仍未找到符合条件的道馆,选择当前列表中系数最低的
        if find_challengeable(ignore_score=True):
            logger.warning("can't find challengeable dokan,select random one")
            self.ui_click(self.I_CENTER_CHALLENGE, self.I_CHALLENGE_ENSURE, interval=1)
            self.ui_click_until_disappear(self.I_CHALLENGE_ENSURE, interval=1)
            self.conf.attack_count_config.del_attack_count(1, self.config.save)
            return True
        return False

    def start_cheering(self) -> None:
        if not self.conf.dokan_config.dokan_auto_cheering_while_cd:
            return
        cd_text = self.O_DOKEN_FAIL_CD.detect_text(self.device.image)
        match = re.search(r'\d+', cd_text)
        remain_seconds = int(match.group()) if match else None
        if not remain_seconds:
            logger.info(f'No remain seconds, exit cheering, cd_text[{cd_text}]')
            return
        cheering_timer = Timer(remain_seconds).start()
        logger.info(f"start cheering, remain seconds:{remain_seconds}s")
        while not cheering_timer.reached():
            self.screenshot()
            # 出现观战标志点击观战
            if self.appear_then_click(self.I_RYOU_DOKAN_CD, interval=2.5):
                sleep(1.5)  # 等待观战列表出现动画
                continue
            if self.is_in_battle(False):
                break
            # 寻找前往按钮并点击
            if self.list_appear_click(self.L_GOTO_CHEERING, interval=3, max_swipe=3):
                continue
            # 没有找到前往(全军覆没或没人上)则随机点击其他位置关闭弹窗
            self.click(pages.random_click(), interval=5)
        else:
            logger.warning('Enter battle to cheer failed')
            return
        logger.info('Enter battle to cheer')
        cheer_cnt = 0
        self.device.stuck_record_clear()
        self.device.stuck_record_add('PAUSE')
        while not cheering_timer.reached():
            self.screenshot()
            battle_end_page = self.detect_page_in(pages.page_battle_result, pages.page_reward, include_global=False)
            if battle_end_page is not None:  # 战斗结束则退出战斗交给上层处理
                logger.info(f'Cheer finish, count[{cheer_cnt}]')
                self.exit_battle(True)
                self.device.stuck_record_clear()
                return
            # 灰色助威
            if self.appear(self.I_RYOU_DOKAN_CHEERING_GRAY, interval=2):
                continue
            # 亮色助威
            if self.appear_then_click(self.I_RYOU_DOKAN_CHEERING, interval=2):
                cheer_cnt += 1
                logger.attr(cheer_cnt, f'cheer, count time[{cheering_timer.current():.1f}s]')
                self.device.stuck_record_clear()
                self.device.click_record_clear()
                self.device.stuck_record_add('PAUSE')
                continue
        # 助威时间到了且道馆还未结束, 则退出观战交给上层重新挑战
        self.exit_battle()

    def abandoned_toppa(self) -> None:
        if self.appear(self.I_DOKAN_ABANDONED_TOPPA):
            self.ui_click(self.I_DOKAN_ABANDONED_TOPPA, stop=self.I_DOKAN_ABANDONED_TOPPA_ENSURE)
            # 点击确认按钮后,会出现突破排名弹窗,需要点击空白区域关闭
            self.ui_click(self.I_DOKAN_ABANDONED_TOPPA_ENSURE, stop=self.I_RYOU_DOKAN_TOPPA_RANK)
            self.ui_click_until_smt_disappear(self.C_DOKAN_TOPPA_RANK_CLOSE_AREA,
                                              stop=self.I_DOKAN_ABANDONED_TOPPA_TITLE,
                                              interval=2)
        # 动画延时
        self.wait_until_appear(self.I_DOKAN_ABANDONED_TOPPA_TITLE, True, 5)
        # 投票放弃突破,一般来说,都主动放弃突破了,基本上点放弃没有错
        if self.appear(self.I_DOKAN_ABANDONED_TOPPA_TITLE):
            if self.appear(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED)
        else:
            # 再战道馆, 保留赏金
            if self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY)

    def switch_soul_in_dokan(self, switch_type: str = None) -> None:
        if switch_type is None:
            return
        switch_soul_dict = {
            'member': {
                'group_team': self.conf.dokan_member_switch_soul.switch_group_team,
                'group_team_name': [self.conf.dokan_member_switch_soul.group_name,
                                    self.conf.dokan_member_switch_soul.team_name]
            },
            'owner': {
                'group_team': self.conf.dokan_owner_switch_soul.switch_group_team,
                'group_team_name': [self.conf.dokan_owner_switch_soul.group_name,
                                    self.conf.dokan_owner_switch_soul.team_name]
            }
        }
        switch_soul_done = getattr(self, f'switch_{switch_type}_soul_done', False)
        if switch_soul_done:
            return
        logger.hr('Start switch soul', 2)
        switch_soul = getattr(self.conf, f'dokan_{switch_type}_switch_soul', None)
        switch_soul_by_name = getattr(self.conf, f'dokan_{switch_type}_switch_soul_by_name', None)
        if switch_soul is not None and switch_soul.enable:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul(switch_soul_dict[switch_type]['group_team'])
            self.goto_page(pages.page_dokan)
        elif switch_soul_by_name is not None and switch_soul_by_name.enable:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul_by_name(switch_soul_dict[switch_type]['group_team_name'][0],
                                         switch_soul_dict[switch_type]['group_team_name'][1])
            self.goto_page(pages.page_dokan)
        else:
            logger.info('Skip switch soul')
        setattr(self, f'switch_{switch_type}_soul_done', True)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
