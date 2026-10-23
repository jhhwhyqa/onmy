# This Python file uses the following encoding: utf-8
"""道馆 / 僵尸寮共用的道馆突破流程。

选馆策略（普通道馆按赏金系数、福利寮按“鑫”图标）、馆主策略、失败再战与
任务结束后的推送由两个入口任务分别实现；选中道馆之后的主循环、页面导航、
战斗、次数读取与下次运行时间在这里共用。
"""
import time
from datetime import datetime, timedelta

from module.base.timer import Timer
from module.exception import GamePageUnknownError, TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import ExitMatcher, GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page_definition import Page


# 主循环里连续识别不到任何页面多久后开始自愈, 以及自愈尝试次数上限
DOKAN_UNKNOWN_PAGE_TIMEOUT = 10.0
DOKAN_UNKNOWN_PAGE_RETRY = 3


class DokanFinishedError(Exception):
    pass


class DokanNotStartedError(Exception):
    pass


class DokanRefreshLimitError(Exception):
    pass


class DokanTaskBase(GameUi, SwitchSoul, GeneralBattle):
    """道馆突破的共享流程；子类负责选馆与策略钩子。"""

    CONFIG_KEY = 'dokan'
    TASK_NAME = 'Dokan'
    # 设置下次运行时间时是否让服务端参与计算；普通道馆原来传 server=False。
    NEXT_RUN_SERVER = True
    # 子类必须指向自己的 tasks/<任务>/page.py 模块。
    pages = None
    conf = None

    # ---------------------------------- 选馆 / 策略钩子 ----------------------------------
    def select_dokan_target(self) -> None:
        """道馆未开启时的选馆流程，由子类实现。"""
        raise NotImplementedError

    def handle_gathering(self) -> None:
        """集结阶段：选择攻击优先级并切换馆员御魂。"""
        self.switch_priority()
        self.prepare_member_soul()

    def prepare_member_soul(self) -> None:
        """馆员战前切换御魂；子类按自己的配置结构实现。"""
        self.switch_soul_in_dokan()

    def switch_soul_in_dokan(self) -> None:
        """切换馆员御魂，由子类实现。"""
        raise NotImplementedError

    def handle_owner_state(self) -> bool:
        """道馆页上识别到馆主战标识时处理；返回 True 表示已处理。"""
        return False

    def handle_member_challenge(self) -> None:
        """馆员战：切御魂并点击挑战直到进入战斗。"""
        self.prepare_member_soul()
        if self.click_until_in_battle():
            self.run_general_battle(self.conf.dokan_member_battle_conf, battle_key='dokan_member')

    def handle_cd(self) -> None:
        """可观的 CD 页面；默认不处理。"""
        pass

    def handle_vote_or_finish(self) -> None:
        """失败投票 / 今日次数耗尽等结算页，由子类实现。"""
        raise NotImplementedError

    def run_owner_battle_from_battle_page(self) -> None:
        """误入战斗页面且识别到馆主战时的处理，由子类实现。"""
        raise NotImplementedError

    def capture_reward_if_visible(self) -> None:
        """每帧截图后的结算捕获钩子；默认不处理。"""
        pass

    def after_run(self, refresh_limit_reached: bool) -> None:
        """任务结束后的收尾钩子；默认不处理。"""
        pass

    def _on_before_run(self) -> None:
        """每次运行开始时的额外重置；默认不处理。"""
        pass

    def should_retry_today(self) -> bool:
        """当天还有一次道馆次数时，是否按 failure_interval 再运行一次。"""
        return self.conf.attack_count_config.remain_attack_count == 1

    # ---------------------------------- 页面 / 战斗 ----------------------------------
    def _register_custom_pages(self) -> None:
        page_battle_result = self.navigator.resolve_page(self.pages.page_battle_result)
        if page_battle_result is None:
            return
        page_battle_result.recognizer = any_of(
            self.I_RYOU_DOKAN_TOPPA_RANK, self.I_RYOU_DOKAN_WIN, page_battle_result.recognizer
        )
        page_battle_result.priority = 75
        page_reward = self.navigator.resolve_page(self.pages.page_reward)
        if page_reward is None:
            return
        page_reward.recognizer = any_of(self.I_RYOU_DOKAN_BATTLE_OVER, page_reward.recognizer)
        page_reward.priority = 75

    def _exit_matcher(self) -> ExitMatcher | None:
        return any_of(self.I_RYOU_DOKAN_CENTER_TOP, self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE)

    def exit_battle(self, skip_first: bool = False) -> bool:
        """
        尝试退出战斗界面。

        1. 普通战斗结束, 连续点击即可退出。
        2. 战斗未开始(右下角有准备按钮), 点击左上角退出并确认。
        3. 馆主战过程中寮友打败馆主, 点击空白区域取消弹窗。
        """
        logger.info("try to quit battle...")
        while True:
            self.screenshot()
            if self.appear(self.I_RYOU_DOKAN_CENTER_TOP):
                return True
            if self.appear(self.I_RYOU_DOKAN_QUIT_BATTLE_ENSURE):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_QUIT_BATTLE_ENSURE)
                return True
            self.screenshot()
            if not self.appear(self.I_RYOU_DOKAN_CENTER_TOP):
                self.click(self.C_DOKAN_BATTLE_QUIT_AREA, interval=3)
                continue
            self.wait_until_appear(self.I_RYOU_DOKAN_CENTER_TOP, True, 3)
        return False

    def click_until_in_battle(self) -> bool:
        """点击挑战直到进入战斗。"""
        timeout_timer = Timer(5).start()
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if timeout_timer.reached():
                break
            self.appear_then_click(self.I_RYOU_DOKAN_START_CHALLENGE, interval=2)
        return False

    def run_on_battle(self) -> None:
        """处理战斗页面逻辑(正常来说不会进入该逻辑)。"""
        if self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_FIRST) or \
                self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND):
            self.dokan_owner_battle = True
            self.run_owner_battle_from_battle_page()
            return
        self.run_general_battle(self.conf.dokan_member_battle_conf, battle_key='dokan_member')

    # ---------------------------------- 主流程 ----------------------------------
    def before_run(self) -> None:
        self.dokan_owner_battle = False
        self.first_master_killed = False
        self.switch_member_soul_done = False
        self.switch_owner_soul_done = False
        self.attack_priority_selected = False
        self.found_dokan_cnt = 0
        self._on_before_run()
        self.pages.page_dokan_rank = self.navigator.add_page(
            Page(self.I_RYOU_DOKAN_TOPPA_RANK, priority=75, register=False)
        )
        self.pages.page_dokan_rank.connect(
            self.pages.page_dokan, random_click, key="page_dokan_rank->page_dokan"
        )

    def run(self) -> None:
        self.before_run()
        self.conf = getattr(self.config.model, self.CONFIG_KEY)
        if self.conf.dokan_config.monday_to_thursday and datetime.now().weekday() >= 4:
            logger.warning("weekend, exit")
            self.next_run(True)
            raise TaskEnd
        # 初始化相关动态参数, 从配置文件读取记录; 没有当天记录时使用默认值
        self.conf.attack_count_config.init_attack_count(callback=self.config.save)
        unknown_page_timer = Timer(10)
        unknown_none_timer = Timer(DOKAN_UNKNOWN_PAGE_TIMEOUT)
        unknown_none_retry = 0
        self.goto_page(self.pages.page_dokan_map)
        refresh_limit_reached = False
        try:
            while True:
                self.screenshot()
                self.capture_reward_if_visible()
                # 只扫 {global, 本任务 category}, 不用 fallback 全量扫描
                current_page = self.get_current_page()
                if current_page is not None:
                    # 识别到页面说明已经脱离未知界面, 重置自愈计时与次数
                    unknown_none_retry = 0
                    unknown_none_timer.reset()
                match current_page:
                    case None:
                        self.device.click_record_clear()
                        self.device.stuck_record_clear()
                        # 持续识别不到说明卡在了未知界面, 交给导航器恢复
                        if not unknown_none_timer.started():
                            unknown_none_timer.start()
                        elif unknown_none_timer.reached():
                            unknown_none_timer = Timer(DOKAN_UNKNOWN_PAGE_TIMEOUT)
                            unknown_none_retry += 1
                            logger.warning(
                                f'[dokan] 持续识别不到任何页面, 尝试恢复 '
                                f'{unknown_none_retry}/{DOKAN_UNKNOWN_PAGE_RETRY}'
                            )
                            if unknown_none_retry >= DOKAN_UNKNOWN_PAGE_RETRY:
                                raise GamePageUnknownError('Dokan cannot detect current page')
                            self.goto_page(self.pages.page_dokan_map)
                        time.sleep(0.5)
                    case self.pages.page_dokan_map:
                        self.run_on_dokan_map()
                    case self.pages.page_dokan:
                        self.run_on_dokan()
                    case self.pages.page_battle_prepare | self.pages.page_battle:
                        self.run_on_battle()
                    case self.pages.page_battle_result:
                        self.click(random_click(ltrb=(False, False, True, False)), interval=1.5)
                    case _:
                        if not unknown_page_timer.started():
                            unknown_page_timer.start()
                        if unknown_page_timer.started() and unknown_page_timer.reached():  # 10秒都是非道馆界面, 则尝试回到道馆
                            unknown_page_timer = Timer(10)
                            self.goto_page(self.pages.page_dokan)
        except DokanFinishedError:
            is_dokan_activated = True
        except DokanRefreshLimitError:
            is_dokan_activated = False
            refresh_limit_reached = True
        except DokanNotStartedError:
            is_dokan_activated = False
        self.goto_page(self.pages.page_main)
        self.next_run(skip_today=refresh_limit_reached, is_dokan_activated=is_dokan_activated)
        self.after_run(refresh_limit_reached)
        raise TaskEnd

    def run_on_dokan_map(self) -> None:
        """道馆地图页面逻辑处理。"""
        if self.appear(self.I_RYOU_DOKAN_FINDING_DOKAN):  # 道馆未开启
            self.select_dokan_target()
            return
        if self.appear(self.I_RYOU_DOKAN_FOUND_DOKAN):  # 道馆已开启
            self.goto_page(self.pages.page_dokan)

    def run_on_dokan(self) -> None:
        """道馆页面逻辑处理。"""
        self.prepare_appear_cache([
            self.I_RYOU_DOKAN_GATHERING,
            self.I_RYOU_DOKAN_MASTER_BATTLE,
            self.I_RYOU_DOKAN_START_CHALLENGE,
            self.I_RYOU_DOKAN_CD,
            self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED,
            self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY,
            self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN,
            self.I_RYOU_DOKAN_TODAY_ATTACK_COUNT,
            self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE,
            self.I_DOKAN_BOSS_WAITING
        ])
        self.device.stuck_record_clear()
        if self.appear(self.I_RYOU_DOKAN_GATHERING):  # 正在集结
            logger.debug("Dokan is gathering...")
            self.handle_gathering()
            self.device.click_record_clear()
            return
        if self.appear(self.I_DOKAN_BOSS_WAITING) or self.appear(self.I_RYOU_DOKAN_MASTER_BATTLE):  # 馆主战标识
            self.dokan_owner_battle = True
        if self.dokan_owner_battle and self.handle_owner_state():
            return
        if not self.appear(self.I_DOKAN_BOSS_WAITING) and self.appear(self.I_RYOU_DOKAN_START_CHALLENGE):  # 可挑战
            self.handle_member_challenge()
            return
        if not self.appear(self.I_DOKAN_BOSS_WAITING) and self.appear(self.I_RYOU_DOKAN_CD):  # 可观战
            self.device.click_record_clear()
            self.handle_cd()
            return
        if (self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY)
                or self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN)
                or self.appear(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED)
                or self.appear(self.I_RYOU_DOKAN_TODAY_ATTACK_COUNT)
                or self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE)):
            self.handle_vote_or_finish()

    # ---------------------------------- 公共工具 ----------------------------------
    def switch_priority(self) -> None:
        """选择优先级。"""
        if self.attack_priority_selected:
            return
        self.goto_page(self.pages.page_dokan_priority)
        self.goto_page(self.pages.page_dokan)
        self.attack_priority_selected = True

    def find_all_element(self, item, offset: tuple) -> list[tuple[int, int, int, int]]:
        """
        NOTE: 仅适配查找道馆列表。

        在当前对象中查找所有匹配的项目，并返回它们的位置信息。
        """
        res_list = []
        while 1:
            if (item.roi_back[0] + item.roi_back[2] > (1280 + offset[2])) or (
                    item.roi_back[1] + item.roi_back[3] > (720 + offset[3])):
                break
            if self.appear(item):
                res_list.append(item.roi_front.copy())
                # 刷新搜索区域, 使用上个搜索结果的Y坐标作为起始点
                item.roi_back = position_offset(item.roi_back, (
                    0, item.roi_front[1] + item.roi_front[3] - item.roi_back[1], 0,
                    item.roi_front[3] - item.roi_back[3]))
            item.roi_back = position_offset(item.roi_back, offset)
        return res_list

    def update_remain_attack_count(self) -> int:
        """根据道馆地图或打完道馆后的寮境界面更新配置中的剩余次数。"""
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
        self.conf.attack_count_config.set_attack_count(count, self.config.save)
        return count

    def creat_dokan(self) -> bool:
        """点击创建道馆，成功建立并关闭道馆信息窗口后返回 True。"""
        while True:
            self.screenshot()
            if self.appear(self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE)
                logger.info("Create Dokan Success")
                return True
            if self.appear(self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE):
                self.ui_click_until_appear_or_timeout(self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE,
                                                      stop=self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE, interval=2, timeout=10)
                continue
            if self.ui_click_until_appear_or_timeout(self.I_RYOU_DOKAN_CREATE_DOKAN,
                                                     self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE, 2, 10):
                continue
            return False

    def next_run(self, skip_today=False, is_dokan_activated=False) -> None:
        """
        设置下次运行时间。

        道馆时间设置为每天固定时间尝试开启; 成功则设置为明天固定时间, 失败则按
        failure_interval 重试; 当天还有一次次数时也会按 failure_interval 再运行一次。
        """
        now = datetime.now()
        run_time = self.conf.dokan_config.dokan_run_time
        run_time_dt = datetime.combine(now.date(), run_time)
        if skip_today:
            if self.conf.dokan_config.monday_to_thursday and now.weekday() >= 4:  # 直接设置下周一的道馆时间
                self.set_next_run(task=self.TASK_NAME, server=self.NEXT_RUN_SERVER,
                                  target=datetime.combine(now.date() + timedelta(days=7 - now.weekday()), run_time))
                return
            self.set_next_run(task=self.TASK_NAME, server=self.NEXT_RUN_SERVER,
                              target=datetime.combine(now.date() + timedelta(days=1), run_time))
            return
        # 道馆没有开启
        if not is_dokan_activated:
            if now < run_time_dt:
                self.set_next_run(task=self.TASK_NAME, server=self.NEXT_RUN_SERVER, target=run_time_dt)
                return
            if now - run_time_dt > timedelta(hours=1):
                self.set_next_run(task=self.TASK_NAME, server=self.NEXT_RUN_SERVER,
                                  target=datetime.combine(now.date() + timedelta(days=1), run_time))
                return
            self.set_next_run(task=self.TASK_NAME, server=self.NEXT_RUN_SERVER,
                              target=now + self.conf.scheduler.failure_interval)
            return
        # 道馆已开启, 当天还有一次次数则稍后再跑
        if self.should_retry_today():
            self.set_next_run(task=self.TASK_NAME, server=self.NEXT_RUN_SERVER,
                              target=now + self.conf.scheduler.failure_interval)
            return
        self.set_next_run(task=self.TASK_NAME, server=self.NEXT_RUN_SERVER,
                          target=datetime.combine(now.date() + timedelta(days=1), run_time))


def position_offset(src, offset: tuple):
    return src[0] + offset[0], src[1] + offset[1], src[2] + offset[2], src[3] + offset[3]
