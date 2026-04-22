# This Python file uses the following encoding: utf-8
# @brief    Ryou Dokan Toppa (阴阳竂道馆突破功能)
# @author   jackyhwei
# @note     draft version without full test
# github    https://github.com/roarhill/oas
import random
import re
import time
from datetime import timedelta
from time import sleep

from cached_property import cached_property
from future.backports.datetime import datetime

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from overrides import override
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle, ExitMatcher, BattleContext, BattleAction, \
    BattleBehaviorScope
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.Component.config_base import Time
from tasks.Dokan.config import Dokan
from tasks.Dokan.dokan_scene import DokanScene, DokanSceneDetector
import tasks.GameUi.page as pages
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_guild, random_click


class ScriptTask(GameUi, SwitchSoul, DokanSceneDetector, GeneralBattle):
    attack_priority_selected: bool = False
    switch_member_soul_done: bool = False
    switch_owner_soul_done: bool = False

    @cached_property
    def _attack_priorities(self) -> list:
        return [self.I_RYOU_DOKAN_ATTACK_PRIORITY_0,
                self.I_RYOU_DOKAN_ATTACK_PRIORITY_1,
                self.I_RYOU_DOKAN_ATTACK_PRIORITY_2,
                self.I_RYOU_DOKAN_ATTACK_PRIORITY_3,
                self.I_RYOU_DOKAN_ATTACK_PRIORITY_4]

    @override
    def _register_custom_pages(self) -> None:
        page_battle_result = self.navigator.resolve_page(pages.page_battle_result)
        if page_battle_result is None:
            return
        page_battle_result.recognizer = pages.any_of(self.I_RYOU_DOKAN_TOPPA_RANK, self.I_RYOU_DOKAN_WIN,
                                                     page_battle_result.recognizer)
        page_battle_result.priority = 75

    @override
    def _exit_matcher(self) -> ExitMatcher | None:
        return pages.any_of(self.I_RYOU_DOKAN_GATHERING, self.I_DOKAN_BOSS_WAITING,
                            self.I_RYOU_DOKAN_START_CHALLENGE, self.I_RYOU_DOKAN_CENTER_TOP,
                            self.I_RYOU_DOKAN_TODAY_ATTACK_COUNT, self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE)

    @override
    def _get_battle_behavior_scopes(self, config: GeneralBattleConfig, battle_key: str) -> dict[str, BattleBehaviorScope]:
        scopes = super()._get_battle_behavior_scopes(config, battle_key)
        if battle_key == 'dokan_owner':
            scopes['green'] = BattleBehaviorScope.ROUND
        return scopes

    def run(self):
        """ 道馆主函数

        :return:
        """
        cfg: Dokan = self.config.dokan

        # 攻击优先顺序
        attack_priority: int = cfg.dokan_config.dokan_attack_priority

        # 周几检测
        if cfg.dokan_config.monday_to_thursday:
            if datetime.now().weekday() >= 4:
                logger.warning("weekend, exit")
                self.next_run(True)
                return
        # 初始化相关动态参数,从配置文件读取相关记录,如果没有当天的记录则设置为默认值
        cfg.attack_count_config.init_attack_count(callback=self.config.save)
        # 道馆是否已开启
        is_dokan_activated = True
        # 进入道馆相关场景
        in_dokan, current_scene = self.get_current_scene(True)
        # 检测不在道馆场景时间
        out_dokan_timer = Timer(60)
        if not in_dokan:
            out_dokan_timer.start()
            self.goto_dokan_scene()
        # 是否已击败馆主第一阵容
        first_master_killed = False
        # 开始道馆流程
        while is_dokan_activated:
            self.screenshot()
            # 检测当前界面的场景（时间关系，暂时没有做庭院、町中等主界面的场景检测, 应考虑在GameUI.game_ui.get_current_page()里实现）
            in_dokan, current_scene = self.get_current_scene(True)
            logger.info(f"in_dokan={in_dokan}, current_scene={current_scene}")
            # 检测到不在道馆场景, 则等待2秒再继续循环
            if not in_dokan:
                if not out_dokan_timer.started():
                    out_dokan_timer.start()
                if out_dokan_timer.reached():
                    logger.warning("long hours away from dokan,exit")
                    break
                logger.info("out of dokan scene,wait for 2 seconds")
                sleep(2)
                continue
            out_dokan_timer.clear()
            # 战斗结束
            if (current_scene == DokanScene.RYOU_DOKAN_SCENE_BATTLE_OVER or
                    current_scene == DokanScene.RYOU_DOKAN_SCENE_WIN):
                # 随便点击个地方退出奖励界面
                self.click(self.C_DOKAN_TOPPA_RANK_CLOSE_AREA, interval=2)
                sleep(2)
                continue
            # 道馆结束弹窗 突破排名
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_TOPPA_RANK:
                self.click(self.C_DOKAN_TOPPA_RANK_CLOSE_AREA, interval=2)
                continue

            # 场景状态：寻找合适道馆中
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_FINDING_DOKAN:
                # 更新可挑战次数 可挑战次数为<=0,当作道馆成功完成
                count = self.update_remain_attack_count()
                if count <= 0:
                    is_dokan_activated = True
                    break
                # 如果没有权限，道馆还未开启
                try_start_dokan = self.config.dokan.dokan_config.try_start_dokan
                if not try_start_dokan:
                    is_dokan_activated = False
                    break
                # NOTE 只在周一尝试建立道馆
                if datetime.now().weekday() == 0:
                    self.creat_dokan()
                # 寻找合适道馆,找不到直接退出
                if not self.find_dokan(self.config.dokan.dokan_config.find_dokan_score):
                    is_dokan_activated = False
                    break
                # 寻找到道馆后等一会页面刷新
                self.wait_until_appear(self.I_RYOU_DOKAN_CENTER_TOP, True, 5)
                continue
            # 场景状态：已找到道馆
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_FOUND_DOKAN:
                self.enter_dokan()
                continue
            # 场景状态：道馆集结中
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_GATHERING:
                logger.debug(f"Ryou DOKAN gathering...")
                # 如果还未选择优先攻击，选一下
                if not self.attack_priority_selected:
                    self.dokan_choose_attack_priority(attack_priority=attack_priority)
                    self.attack_priority_selected = True
                    continue
                self.switch_soul_in_dokan('member')
                self.device.click_record_clear()
                self.device.stuck_record_clear()
                sleep(2)
                continue
            # 场景状态：等待馆主战开始
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_BOSS_WAITING:
                logger.debug(f"Ryou DOKAN boss battle waiting...")
                self.switch_soul_in_dokan('owner')
                self.device.stuck_record_clear()
                if cfg.dokan_config.try_start_dokan and cfg.attack_count_config.attack_dokan_master_count() == 0:
                    # 有权限且当前道馆突破 不再打馆主,直接放弃突破
                    self.abandoned_toppa()
                # 等待馆主战开启
                sleep(2)
                continue
            # 场景状态：在寮境,馆主战进行中,且右下角有挑战
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_MASTER_BATTLING:
                count = cfg.attack_count_config.attack_dokan_master_count()
                logger.info(f"{current_scene} dokan_master_count:{count},first_master_killed:{first_master_killed}")
                if (count - (1 if first_master_killed else 0)) > 0:
                    logger.info("start Master_first")
                    self.click(self.I_RYOU_DOKAN_START_CHALLENGE, interval=2)
                    continue
                # 放弃突破
                if cfg.dokan_config.try_start_dokan:
                    # 有权限且当前道馆突破 不再打馆主,直接放弃突破
                    self.abandoned_toppa()
                continue
            # 场景状态：检查右下角有没有挑战？通常是失败了，并退出来到集结界面，可重新开始点击右下角挑战进入战斗
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_START_CHALLENGE:
                # TODO: 暂时不知道现在打的是什么, 只能按照馆员御魂切换
                self.switch_soul_in_dokan('member')
                self.click(self.I_RYOU_DOKAN_START_CHALLENGE, interval=1)
                continue
            # 场景状态：馆主第一阵容 且战斗未开始
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_BATTLE_MASTER_FIRST:
                count = cfg.attack_count_config.attack_dokan_master_count()
                logger.info(f"{current_scene} dokan_master_count:{count}")
                battle_success = self.run_general_battle(cfg.dokan_owner_battle_conf, battle_key='dokan_owner')
                if count == 1 and battle_success:
                    # TEST 只打一次 应该是还在战斗界面 处于未准备界面(RYOU_DOKAN_SCENE_BATTLE_MASTER_SECOND)
                    first_master_killed = True
                    continue
                # 战斗失败的话 需要点击几次,退出战场界面(NOTE 此为猜测,具体情况不确定)
                # count = 0 时,正常不应进入此分支,可直接退出
                # count =2 时,dokan_battle 中 会打第一 第二 阵容,
                #          成功打掉第二阵容,应该有奖励图片,可 尝试退出
                #          攻打过程中失败,可尝试退出
                #          攻打过程中,其他人打完了,可尝试退出
                # 直接尝试退出
                self.quit_battle()
                continue
            # 场景状态：馆主第二阵容,且 战斗未开始
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_BATTLE_MASTER_SECOND:
                logger.warning("Second Master Battle")
                first_master_killed = True
                if cfg.attack_count_config.attack_dokan_master_count() < 2:
                    # 退出战斗界面
                    self.quit_battle()
                    continue
                self.run_general_battle(cfg.dokan_owner_battle_conf, battle_key='dokan_owner')
                self.quit_battle()
                continue
            # 场景状态：进入战斗，待开始
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_IN_FIELD:
                # 战斗
                self.run_general_battle(cfg.dokan_member_battle_conf, battle_key=f'dokan_member')
                # 战斗结束,尝试退出战斗界面
                self.quit_battle()
                continue
            # 场景状态：如果CD中，开始加油
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_CD:
                logger.info(f"Fail CD: start cheering={cfg.dokan_config.dokan_auto_cheering_while_cd}..")
                if cfg.dokan_config.dokan_auto_cheering_while_cd:
                    self.start_cheering()
                continue
            # 投票 是否放弃突破   放弃/继续
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_ABANDON_VOTE:
                # 一般来说,都是点放弃
                self.click(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED)
                continue
            # 投票 再战道馆/保留赏金
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_FAILED_VOTE:
                # 每天打一次的直接 选择 保留赏金,
                # 打两次的,第一次选择 继续挑战,第二次没有选项
                if cfg.attack_count_config.daily_attack_count == 2:
                    if self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN):
                        self.ui_click_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN)
                else:
                    if self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY):
                        logger.info("Dokan challenge failed: vote for keep the awards")
                        self.ui_click_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY)
                continue
            # 场景状态：道馆已经结束
            if current_scene == DokanScene.RYOU_DOKAN_SCENE_FINISHED:
                logger.info("Dokan challenge finished, exit Dokan")
                # 更新配置
                self.update_remain_attack_count()
                break
            logger.info(f"scene Without handler, skipped")
            continue

        # 保持好习惯，一个任务结束了就返回到庭院，方便下一任务的开始
        self.goto_main()
        self.next_run(skip_today=False, is_dokan_activated=is_dokan_activated)
        raise TaskEnd

    def dokan_choose_attack_priority(self, attack_priority: int) -> bool:
        """ 选择优先攻击
        : return
        """
        logger.hr('Try to choose attack priority')
        max_try = 5
        if not self.appear_then_click(self.I_RYOU_DOKAN_ATTACK_PRIORITY, interval=2):
            logger.error(f"can not find dokan priority option button, choose attack priority process skipped")
            return False
        logger.info(f"start select attack priority: {attack_priority}, remain try: {max_try}")
        try:
            target_attack = self._attack_priorities[attack_priority]
        except:
            target_attack = self._attack_priorities[0]
        while 1:
            self.screenshot()
            if max_try <= 0:
                logger.warn("give up priority selection!")
                break
            if self.appear_then_click(target_attack, interval=1.8):
                self.attack_priority_selected = True
                logger.info(f"selected attack priority: {attack_priority}")
                break
            max_try -= 1
        return True

    def goto_main(self):
        """ 保持好习惯，一个任务结束了就返回庭院，方便下一任务的开始或者是出错重启

            任意庭院->道馆的界面返回庭院
        """
        while 1:
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN):
                break
            if self.appear(self.I_RYOU_DOKAN_QUIT_BATTLE_ENSURE):
                # 借用下,猜测是一样的确定按钮,如果不一样,会卡住
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_QUIT_BATTLE_ENSURE, interval=2)
                continue
            if self.appear(self.I_RYOU_DOKAN_DOKAN_QUIT):
                self.click(self.I_RYOU_DOKAN_DOKAN_QUIT, interval=3)
                continue
            if self.appear(self.I_BACK_BL):
                self.click(self.I_BACK_BL, interval=3)
                continue
            if self.appear(self.I_BACK_Y):
                self.click(self.I_BACK_Y, interval=3)
                continue

    def goto_dokan_scene(self):
        # 截图速度太快会导致在道馆-神社之间一直循环无法退出,故设置截图间隔
        self.device.screenshot_interval_set(0.3)
        while 1:
            self.screenshot()
            in_dokan, cur_scene = self.get_current_scene()
            if in_dokan:
                break
            if cur_scene == DokanScene.RYOU_DOKAN_RYOU:
                self.ui_click_until_disappear(self.I_RYOU_SHENSHE)
                continue
            if cur_scene == DokanScene.RYOU_DOKAN_SHENSHE:
                self.ui_click_until_disappear(self.I_RYOU_DOKAN, interval=1)
                continue
            if not in_dokan:
                self.goto_page(page_guild)
                continue
        self.device.screenshot_interval_set()
        return True

    def enter_dokan(self):
        """
            如果道馆已经开启,进入寮境
        """
        try_count = 0
        while try_count < 5:
            self.screenshot()
            _, cur_scene = self.get_current_scene()
            if cur_scene != DokanScene.RYOU_DOKAN_SCENE_FOUND_DOKAN:
                return False
            pos = self.O_DOKAN_MAP.ocr_full(self.device.image)
            if pos == (0, 0, 0, 0):
                logger.info(f"failed to find {self.O_DOKAN_MAP.keyword}")
            else:
                # 取中间
                x = pos[0] + pos[2] / 2
                # 往上偏移20
                y = pos[1] - 20

                logger.info("ocr detect result pos={pos}, try click pos, x={x}, y={y}")
                self.device.click(x=x, y=y)
            try_count += 1
            time.sleep(1)
        return True

    def find_dokan(self, score=4.6):
        """
        寻找符合条件的道馆进行挑战。
    
        参数:
        score (float): 赏金与人数比值的阈值，默认为4.6。
    
        返回:
        bool: 是否找到了符合条件的道馆并进行挑战。
        """

        #
        is_indokan, cur_scene = self.get_current_scene()
        if not is_indokan:
            return False
        if cur_scene != DokanScene.RYOU_DOKAN_SCENE_FINDING_DOKAN:
            return True

        # 刷新按钮点击次数
        num_fresh = 0
        # 备份一些重要的ROI区域，以便在循环中恢复
        backup = {'i_point_bounty': self.I_RIGHTPAD_POINT_BOUNTY.roi_back,
                  # 'o_dokan_rightpad_bounty':self.O_DOKAN_RIGHTPAD_BOUNTY.roi,
                  'i_point_people_num': self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back}

        def restore_roi():
            self.I_RIGHTPAD_POINT_BOUNTY.roi_back = backup['i_point_bounty']
            self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back = backup['i_point_people_num']

        def find_challengeable(ignore_score=False):
            """
                查找当前列表状态(一般为4个)中符合条件的道馆,并点击使其显示挑战按钮
            @param ignore_score: 是否忽略道馆系数限制, - True:   那么选择当前列表状态系数最低的那个,点击显示挑战按钮
                                                   - False:  如果存在系数符合条件的,点击并显示挑战按钮
                                                            如果全部不符合条件,不进行任何操作,返回时,不显示挑战按钮
            @type ignore_score: float
            @return:
            @rtype:
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

                # 点击使挑战按钮消失的区域(C_DOKAN_CANCEL_SELECT_DOKAN), 点击可能点击到其他寮,
                # 因此需要在此处多点几次,直到挑战按钮消失,
                # 又因为出现挑战按钮动画时长较长,因此需要耗时
                self.screenshot()
                while self.appear(self.I_CENTER_CHALLENGE):
                    self.click(self.C_DOKAN_CANCEL_SELECT_DOKAN, interval=1.5)
                    self.wait_animate_stable(self.C_DOKAN_CANCEL_SELECT_DOKAN_CHECK_ANIMATE, interval=0.5, timeout=1.5)

                # 获取赏金金额
                self.O_DOKAN_RIGHTPAD_BOUNTY.roi = self.position_offset(item, (0, 0, 100, 0))
                bounty = self.O_DOKAN_RIGHTPAD_BOUNTY.ocr(self.device.image)
                tmp = re.search(r'(\d+)', bounty)
                if not tmp:
                    logger.warning(f"can't find bounty,item = {item},ocr bounty={bounty}")
                    continue
                bounty = float(tmp.group())
                # 扩大搜索区域,防止找不到
                self.I_RIGHTPAD_POINT_BOUNTY.roi_back = self.position_offset(item, (-10, -10, 20, 20))
                # Note: 道馆不可挑战时(被别的寮打了),8秒后跳过
                if not self.ui_click_until_appear_or_timeout(self.I_RIGHTPAD_POINT_BOUNTY, self.I_CENTER_CHALLENGE,
                                                             interval=1.5, timeout=8):
                    logger.info(f"can't find challenge button,idx={idx} item={item}")
                    # 道馆不可挑战,挑战按钮不会弹出 ,直接进行下一个
                    continue
                # 获取防守人数
                self.screenshot()
                if not self.appear(self.I_CENTER_POINT_PEOPLE_NUMBER):
                    logger.warning(f"can't find point people number image, item={item}")
                    continue
                self.O_DOKAN_CENTER_PEOPLE_NUMBER.roi = self.position_offset(
                    self.I_CENTER_POINT_PEOPLE_NUMBER.roi_front,
                    (0, 0, 0, 30))
                p_num = self.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text(self.device.image)
                tmp = re.search(r"(\d+)", p_num)
                if not tmp:
                    logger.warning(f"can't find people number in ocr result,item={item}, p_num={p_num}")
                    continue
                p_num = float(tmp.group())

                logger.info(f"==================="
                            f"bounty:{bounty},people_num:{p_num},score:{bounty / p_num}"
                            f"===================")

                item_score = bounty / p_num
                if item_score < min_score:
                    min_score = item_score
                    idx_selected = idx
                # 大于系数 或者 系数过小(文字识别错误导致)
                if item_score > score or item_score < 1.5:
                    logger.info("click to making challenge disappear")
                    continue
                if p_num < self.config.dokan.dokan_config.min_people_num:
                    logger.info("people num too small")
                    continue
                if bounty < self.config.dokan.dokan_config.min_bounty:
                    logger.info("bounty too small")
                    continue
                # 馆主不是修习等级的
                if not self.appear(self.I_CENTER_GUANZHU_XIUXI):
                    continue
                logger.info(f"find_dokan: bounty:{bounty},people_num:{p_num},score:{bounty / p_num}")
                return True
            # 在所有列表中都没有符合的,且忽略系数限制,那么就选择最低分数的那个,点击显示挑战按钮
            if ignore_score:
                x, y, w, h = bounty_list[idx_selected]
                while 1:
                    self.screenshot()
                    if self.appear(self.I_CENTER_CHALLENGE):
                        return True
                    self.device.click(x, y)
                    sleep(0.5)
            return False

        while num_fresh < self.config.dokan.dokan_config.find_dokan_refresh_count:
            for i in range(3):
                sleep(3)
                if find_challengeable():
                    logger.info("find challengeable dokan")
                    self.ui_click(self.I_CENTER_CHALLENGE, self.I_CHALLENGE_ENSURE, interval=1)
                    self.ui_click_until_disappear(self.I_CHALLENGE_ENSURE, interval=1)
                    # 更新可挑战次数
                    self.config.dokan.attack_count_config.del_attack_count(1, self.config.save)
                    # 恢复初始位置信息,防止下次使用出错
                    restore_roi()
                    return True
                # 滑动道馆列表
                self.swipe(self.S_DOKAN_LIST_UP)

            # 恢复初始位置信息,防止下次使用出错
            restore_roi()
            logger.info("=========refresh dokan list=========")
            self.ui_click(self.C_DOKAN_REFRESH, self.I_REFRESH_ENSURE, interval=1)
            self.ui_click_until_disappear(self.I_REFRESH_ENSURE, interval=1)

            logger.info("Refresh Done")
            num_fresh += 1

        # 刷新次数用完,仍未找到符合条件的道馆,选择当前列表(约4个)中系数最低的
        if find_challengeable(ignore_score=True):
            logger.warning("can't find challengeable dokan,select random one")
            self.ui_click(self.I_CENTER_CHALLENGE, self.I_CHALLENGE_ENSURE, interval=1)
            self.ui_click_until_disappear(self.I_CHALLENGE_ENSURE, interval=1)
            # 更新可挑战次数
            self.config.dokan.attack_count_config.del_attack_count(1, self.config.save)
            return True
        return False

    def creat_dokan(self):
        # 点击创建道馆
        # 当 成功建立道馆并关闭道馆信息窗口后退出
        #  或 点击创建道馆按钮无反应(道馆已经建立的情况下),5秒后退出
        while True:
            self.screenshot()
            if self.appear(self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE)
                logger.info("Create Dokan Success")
                break
            if self.appear(self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE):
                self.ui_click_until_appear_or_timeout(self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE,
                                                      stop=self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE, interval=2, timeout=10)
                continue
            if self.ui_click_until_appear_or_timeout(self.I_RYOU_DOKAN_CREATE_DOKAN,
                                                     self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE, 2, 10):
                continue
            break

    def find_all_element(self, item, offset: tuple) -> list[tuple[int, int, int, int]]:
        """
        NOTE: 仅适配查找道馆列表
       在当前对象中查找所有匹配的项目，并返回它们的信息列表。

       此函数的目的是通过循环搜索和匹配给定的项目，并将匹配的项目信息存储到一个列表中。
       如果项目出现，则将其添加到列表中，并根据预定义的规则调整项目的位置。

       参数:
       - item: 需要查找的项目。
       - offset: 如果当前区域查找不到,扩大查找区域的大小

       返回值:
       返回一个包含所有匹配项目信息的列表。
       """
        res_list = []
        while 1:
            if (item.roi_back[0] + item.roi_back[2] > (1280 + offset[2])) or (
                    item.roi_back[1] + item.roi_back[3] > (720 + offset[3])):
                break
            if self.appear(item):
                res_list.append(item.roi_front.copy())
                # 刷新搜索区域,使用上个搜索结果的Y坐标作为起始点的Y坐标,搜索结果的高度作为起始搜索高度
                item.roi_back = self.position_offset(item.roi_back, (
                    0, item.roi_front[1] + item.roi_front[3] - item.roi_back[1], 0,
                    item.roi_front[3] - item.roi_back[3]),
                                                     )
            item.roi_back = self.position_offset(item.roi_back, offset)
        return res_list

    def start_cheering(self):
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
                sleep(1)  # 等待一下寮排名展示动画
                continue
            # 寻找前往按钮并点击
            if self.list_appear_click(self.L_GOTO_CHEERING, interval=3, max_swipe=3):
                break
            # 没有找到前往(全军覆没or没人上)则随机点击其他位置关闭弹窗
            self.click(random_click(), interval=5)
        logger.info('Enter battle to cheer')
        cheer_cnt = 0
        self.device.stuck_record_clear()
        self.device.stuck_record_add('PAUSE')
        while not cheering_timer.reached():
            self.screenshot()
            battle_end_page = self.detect_page_in(pages.page_battle_result, pages.page_reward, include_global=False)
            if battle_end_page is not None:  # 战斗结束则退出战斗交给上层处理
                self.run_general_battle(battle_key=f'dokan_cheering')
                logger.info(f'Cheer finish, count[{cheer_cnt}]')
                self.device.stuck_record_clear()
                return
            # 灰色助威
            if self.appear(self.I_RYOU_DOKAN_CHEERING_GRAY, interval=2):
                sleep(random.uniform(2, 4))
                continue
            # 亮色助威
            if self.appear_then_click(self.I_RYOU_DOKAN_CHEERING, interval=2):
                cheer_cnt += 1
                logger.attr(cheer_cnt, f'cheer, count time[{cheering_timer.current():.1f}s]')
                self.device.stuck_record_clear()
                self.device.click_record_clear()
                self.device.stuck_record_add('PAUSE')
                sleep(random.uniform(2, 4))
                continue
        # 助威时间到了且道馆还未结束, 则退出观战交给上层重新挑战
        self.exit_battle()
        self.device.stuck_record_clear()

    def update_remain_attack_count(self) -> int:
        """
        根据道馆地图界面 或 打完道馆后 的寮境界面,更新配置信息
        @return:
        @rtype:
        """
        self.screenshot()
        count = -1
        if self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_ZERO) or self.appear(
                self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE):
            logger.info("I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_ZERO/DONE found")
            count = 0
        elif self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_ONE):
            logger.info("I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_ONE found")
            count = 1
        elif self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_TWO):
            logger.info("I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_TWO found")
            count = 2
        else:
            logger.info("dont find REMAIN_ATTACK_COUNT PIC")
            count = -1
        self.config.dokan.attack_count_config.set_attack_count(count, self.config.save)
        return count

    def quit_battle(self):
        """
            尝试退出战斗界面
            1. 普通战斗结束,连续点击即可退出
                a. 存在战斗奖励
                b. 战斗失败,
            2. 在战斗界面,但是战斗还未开始(右下角有准备按钮)
                需要点击左上角退出按钮,然后点击确定
            3. 馆主战斗过程中,寮友打败馆主,弹出框体,可点击空白区域取消该框体.
            综上,点击左上角退出按钮区域
        """
        logger.info("try to quit battle...")
        while True:
            self.screenshot()
            if self.appear(self.I_RYOU_DOKAN_CENTER_TOP):
                break
            if self.appear(self.I_RYOU_DOKAN_QUIT_BATTLE_ENSURE):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_QUIT_BATTLE_ENSURE)
                break
            # 退出时,意外弹出"确认退出集结场景" 弹窗,导致卡住
            # 只能怀疑是上面两个appear的耗时 导致screenshot 过时导致错误点击
            # TODO: 待验证
            # 还有一种可能:在退出战斗过程中,在过场图出现前,点击左上角退出按钮,会导致该弹窗弹出(恶心)
            self.screenshot()
            if not self.appear(self.I_RYOU_DOKAN_CENTER_TOP):
                self.click(self.C_DOKAN_BATTLE_QUIT_AREA, interval=3)
                continue
            self.wait_until_appear(self.I_RYOU_DOKAN_CENTER_TOP, True, 3)

    def abandoned_toppa(self):
        if self.appear(self.I_DOKAN_ABANDONED_TOPPA):
            self.ui_click(self.I_DOKAN_ABANDONED_TOPPA, stop=self.I_DOKAN_ABANDONED_TOPPA_ENSURE)
            # 点击确认按钮后,会出现突破排名弹窗,需要点击空白区域关闭
            self.ui_click(self.I_DOKAN_ABANDONED_TOPPA_ENSURE, stop=self.I_RYOU_DOKAN_TOPPA_RANK)
            self.ui_click_until_smt_disappear(self.C_DOKAN_TOPPA_RANK_CLOSE_AREA,
                                              stop=self.I_DOKAN_ABANDONED_TOPPA_TITLE,
                                              interval=2)
        # 动画延时
        self.wait_until_appear(self.I_DOKAN_ABANDONED_TOPPA_TITLE, True, 5)
        # 投票放弃突破,一般来说,都主动放弃突破了,基本上点放弃没有错(虽然项目中做了继续的按钮图)
        if self.appear(self.I_DOKAN_ABANDONED_TOPPA_TITLE):
            if self.appear(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED)
        else:
            # 再战道馆, 保留赏金
            if self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY)

    def switch_soul_in_dokan(self, switch_type: str = None):
        if self.switch_member_soul_done and self.switch_owner_soul_done:
            return
        if switch_type is None:
            return
        if switch_type == 'member' and not self.switch_member_soul_done:
            if self.config.dokan.dokan_member_switch_soul.enable:
                logger.info("start switch member soul...")
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_SHIKIGAMI, interval=2)
                self.run_switch_soul(self.config.dokan.dokan_member_switch_soul.switch_group_team)
            if self.config.dokan.dokan_member_switch_soul.enable_switch_by_name:
                logger.info("start switch member soul...")
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_SHIKIGAMI, interval=2)
                self.run_switch_soul_by_name(self.config.dokan.dokan_member_switch_soul.group_name,
                                             self.config.dokan.dokan_member_switch_soul.team_name)
            self.switch_member_soul_done = True
            self.click(self.I_UI_BACK_YELLOW, interval=1)
        elif switch_type == 'owner' and not self.switch_owner_soul_done:
            if self.config.dokan.dokan_owner_switch_soul.enable:
                logger.info("start switch owner soul...")
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_SHIKIGAMI, interval=2)
                self.run_switch_soul(self.config.dokan.dokan_owner_switch_soul.switch_group_team)
            if self.config.dokan.dokan_owner_switch_soul.enable_switch_by_name:
                logger.info("start switch owner soul...")
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_SHIKIGAMI, interval=2)
                self.run_switch_soul_by_name(self.config.dokan.dokan_owner_switch_soul.group_name,
                                             self.config.dokan.dokan_owner_switch_soul.team_name)
            self.switch_owner_soul_done = True
            self.click(self.I_UI_BACK_YELLOW, interval=1)

    def next_run(self, skip_today=False, is_dokan_activated=False):
        """
            设置下次运行时间
            该函数假定道馆时间设置为:每天固定时间尝试开启(例如:19:00),成功后设置为明天固定时间(例如19:00)
                                失败则在短时间(例如:2分钟)内再次尝试开启道馆任务
            此假定应该符合绝大多数人需求,如果存在其他需求,,,help yourself

        @param skip_today: 是否跳过今天,True->当作当天的道馆已成功打掉,False->无效
                            为了跳过周五->周天
        @type skip_today: bool
        @param is_dokan_activated:
        @type is_dokan_activated: bool
        @return:
        @rtype:
        """
        now = datetime.now()
        run_time: Time = self.config.model.dokan.dokan_config.dokan_run_time
        run_time_dt = datetime.combine(now.date(), run_time)
        if skip_today:
            self.set_next_run(task="Dokan", server=False,
                              target=datetime.combine(now.date() + timedelta(days=1), run_time))
            return
        # 道馆没有开启
        if not is_dokan_activated:
            # 在服务器时间之前,设置为服务器时间
            if now < run_time_dt:
                self.set_next_run(task="Dokan", server=False, target=run_time_dt)
                return
            # 在服务器时间之后,如超过1小时,则直接当作成功;未超过则当作失败
            if now - run_time_dt > timedelta(hours=1):
                self.set_next_run(task="Dokan", server=False,
                                  target=datetime.combine(now.date() + timedelta(days=1), run_time))
                return
            # 时间在道馆开启时间附近，failure_interval后执行
            self.set_next_run(task="Dokan", server=False, target=now + self.config.dokan.scheduler.failure_interval)
        # 道馆已开启
        if is_dokan_activated:
            # 如果打两次,当前是第一次,设置为failure_interval后运行
            if self.config.dokan.attack_count_config.remain_attack_count == 1 and self.config.dokan.attack_count_config.daily_attack_count == 2:
                self.set_next_run(task="Dokan", server=False, target=now + self.config.dokan.scheduler.failure_interval)
                return
            # 其余情况当作成功
            self.set_next_run(task="Dokan", server=False,
                              target=datetime.combine(now.date() + timedelta(days=1), run_time))

    def position_offset(self, src, offset: tuple):
        return (src[0] + offset[0], src[1] + offset[1]
                    , src[2] + offset[2], src[3] + offset[3])


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常2')
    d = Device(c)
    t = ScriptTask(c, d)
    t.green_mark_name('我是天照')
