import re

from datetime import datetime, timedelta
from time import sleep

from module.base.timer import Timer
from module.logger import logger
from module.base.protect import random_sleep
from module.exception import RequestHumanTakeover, TaskEnd
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.action import conditional_action
from tasks.DailyTrifles.script_task import ScriptTask as DailyTriflesScriptTask
from tasks.TalismanPass.script_task import ScriptTask as TalismanPassScriptTask
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.GameUi.page import (
    page_main,
    page_exploration,
    page_mall,
    page_team,
    page_daily,
)
from tasks.LevelRush.page import page_rookie_act, page_achievement
from tasks.Exploration.config import ExplorationLevel
from tasks.Exploration.assets import ExplorationAssets
from tasks.LevelRush.assets import LevelRushAssets
from tasks.LevelRush.config import LevelRushConfig
from tasks.Restart.assets import RestartAssets


class ScriptTask(
    GeneralBattle,
    DailyTriflesScriptTask,
    TalismanPassScriptTask,
    LevelRushAssets,
):
    _OCR_CHAR_FIX = str.maketrans(
        {
            '+': '十',
            '＋': '十',
            't': '十',
            'T': '十',
            '-': '一',
            '—': '一',
            '_': '一',
            'l': '一',
            'I': '一',
            'ニ': '二',
            '人': '八',
            '入': '八',
            '丸': '九',
            '几': '九',
            '大': '六',
            '穴': '六',
        }
    )
    # 章节顺序表（与 Exploration 的枚举保持一致，从前往后难度递增）
    _EXPLORATION_CHAPTERS = [
        '第一章',
        '第二章',
        '第三章',
        '第四章',
        '第五章',
        '第六章',
        '第七章',
        '第八章',
        '第九章',
        '第十章',
        '第十一章',
        '第十二章',
        '第十三章',
        '第十四章',
        '第十五章',
        '第十六章',
        '第十七章',
        '第十八章',
        '第十九章',
        '第二十章',
        '第二十一章',
        '第二十二章',
        '第二十三章',
        '第二十四章',
        '第二十五章',
        '第二十六章',
        '第二十七章',
        '第二十八章',
    ]

    # 中间章节用来判定执行体力补给任务
    _MID_CHAPTER = '第十二章'
    _MID_CHAPTER_INDEX = _EXPLORATION_CHAPTERS.index(_MID_CHAPTER)
    # 初始阵容（SP 姑获鸟）的稳定上限：困难十五章
    _MAX_CHAPTER = '第十五章'
    _MAX_CHAPTER_INDEX = _EXPLORATION_CHAPTERS.index(_MAX_CHAPTER)
    # 默认最大章节：困难二十八章
    _DEFAULT_CHAPTER = '第二十八章'
    conf: LevelRushConfig

    def before_run(self):
        page_main.add_enter_failure_hooks(
            conditional_action(
                condition=LevelRushAssets.I_PHONE_BIND,
                action=LevelRushAssets.I_PHONE_BIND,
            ),
            conditional_action(
                condition=LevelRushAssets.I_PHONE_BIND_CANCEL,
                action=LevelRushAssets.I_PHONE_BIND_CANCEL,
            ),
        )

    def run(self):
        self.before_run()
        self.conf = self.config.model.level_rush
        self.stop_flag = False

        # 七级前流程
        if not self.conf.level_rush_config.level_7_mark:
            # 1.七级前的手动剧情流程
            self._run_before_level_7()
            # 2.达到七级领取邮件初始奖励
            self.run_pickup_email()
            # 3.前往新手活动借取姑获鸟
            self._run_borrow_gh_bird()
            # 4.领取新手体力奖励
            self._get_rookie_reward()

        # 过剧情解锁十五章
        if not (
            self.config.level_rush.level_rush_config.exploration_chapter_max_15_enable
            and self.config.exploration.exploration_config.exploration_level
            == '第十五章'
        ):
            self._run_storyline()

        # 触发了跳过剧情就判定是否需要停止任务
        # 到达40级就停止任务
        cu_level = self._get_current_level()
        if (cu_level >= 40 and cu_level <= 60) or (
            self.config.level_rush.level_rush_config.skip_to_30_stop_enable
            and self.stop_flag
        ):
            # 达到目标等级后本任务不再需要，把自己在实例配置里禁用，当作一次性任务
            self.config.level_rush.scheduler.enable = False
            self.config.level_rush.level_rush_config.level_7_mark = False
            self.config.level_rush.level_rush_config.assist_up_mark = False
            self.config.level_rush.level_rush_config.skip_to_30_mark = False
            self.config.level_rush.level_rush_config.get_achievement_reward_mark = False
            self.config.exploration.exploration_config.exploration_level = (
                self._DEFAULT_CHAPTER
            )
            self.config.save()
            raise TaskEnd('LevelRush')

        chapter = self.config.exploration.exploration_config.exploration_level
        # 体力够就来一轮探索
        if not self._get_current_sushi():
            self._run_exploration()
        # 体力不够且做完了十二章剧情才会触发下面的流程，正常情况500体力应该是足够到这里的
        elif self._EXPLORATION_CHAPTERS.index(chapter) >= self._MID_CHAPTER_INDEX:
            # 一次性流程
            if not self.config.level_rush.level_rush_config.get_achievement_reward_mark:
                # 1.领取邮件中的实名奖励200勾玉
                self.run_pickup_email()
                # 2.领取花合站和成就里的奖励大约200勾玉
                self._run_before_buy()
                # 3.购买新手体力礼包
                self._run_buy_rookie_gift()
                # 4.过完第一次经验妖怪教程
                self._run_exp_youkai_1st()
                # 5.把剩下的勾玉全买体力
                self._run_buy_sushi()
                # 正常做完保存配置
                self.config.level_rush.level_rush_config.get_achievement_reward_mark = (
                    True
                )
                self.config.save()
            else:
                # 6.后续体力不足100就尝试运行经验妖怪
                self.run_experienceyoukai()
                # 7.体力不足只能等待体力回复，标记失败，4小时cd
                logger.info(f"体力不足100，4小时后再次尝试")
                self._task_end(False)
        # 有体力的情况下正常结束本轮任务，标记成功，5分钟cd
        logger.info(f"本轮正常结束，即将执行下一轮")
        self._task_end(True)

    def run_experienceyoukai(self):
        "运行经验妖怪"
        self.config.script_set_arg(
            task='ExperienceYoukai',
            group='Scheduler',
            argument='enable',
            value=True,
        )
        self.config.task_call('ExperienceYoukai')

    def _run_exp_youkai_1st(self):
        "过完第一次经验妖怪教程"
        from tasks.ExperienceYoukai.assets import ExperienceYoukaiAssets

        logger.hr('run exp youkai tutorial', 2)
        self.goto_page(page_team)
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_GUIDE_FAN, interval=1.2):
                continue
            if self.appear_then_click(self.I_EXP_YOUKAI_CREATE, interval=1.2):
                continue
            if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1.2):
                continue
            if self.appear(ExperienceYoukaiAssets.I_EXP_WIN):
                self.click(random_click(ltrb=(True, False, False, False)), interval=1.5)
                continue
            if self.get_current_page(page_main) == page_main:
                logger.info(f"First exp youkai finished")
                break
            if self.appear(self.I_CHECK_TEAM):
                logger.info(
                    f"Level is more 31 level, first exp youkai should be finished, exit"
                )
                break
        self.goto_page(page_main)

    def _run_buy_rookie_gift(self):
        "购买新手礼包补充1000体力"
        logger.hr('buy rookie gift', 2)
        self.goto_page(page_mall, confirm_wait=2.5)
        self.ui_click(self.I_MALL_GOTO_ROOKIE_MALL, self.I_SIDE_CHECK_ROOKIE_MALL)
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_ROOKIE_SUSHI_GIFT, interval=1.2):
                continue
            if self.ui_click_until_disappear(self.I_BUY_SUSHI_GIFT, interval=1.2):
                continue
            if not self.appear(self.I_BUY_SUSHI_GIFT) and not self.appear(
                self.I_ROOKIE_SUSHI_GIFT
            ):
                logger.info(f"Buy rookie sushi gift finished")
                break

    def _run_buy_sushi(self):
        "尝试购买体力2次"
        logger.hr('buy sushi', 2)
        self.config.daily_trifles.trifles_config.buy_sushi_count = 2
        self.run_buy_sushi()

    def _run_before_buy(self):
        "领取成就和花合战里的奖励大约200勾玉"
        logger.hr('get jade', 2)
        self.goto_page(page_daily)
        if self.in_task():
            self.get_all()

        self.goto_page(page_achievement)
        loop = 0
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_GET_ACHIEVEMENT_REWARD, interval=1.2):
                self.device.click_record_clear()
                continue
            if not self.appear(
                self.I_GET_ACHIEVEMENT_REWARD
            ) and self.appear_then_click(self.I_ACHIEVEMENT_MENU_CLOSE, interval=1.2):
                self.device.click_record_clear()
                continue
            if self.appear_then_click(self.I_ACHIEVEMENT_REWARD_EXIST, interval=1.2):
                self.device.click_record_clear()
                continue
            if loop >= 3:
                break
            if not self.appear(self.I_GET_ACHIEVEMENT_REWARD) and not self.appear(
                self.I_ACHIEVEMENT_REWARD_EXIST
            ):
                loop += 1
        logger.info(f"Achievement reward get finish")
        self.goto_page(page_main)

    def _task_end(self, success: bool):
        """
        结束当前 LevelRush 任务并设置下次运行时间
        成功时延迟 10 分钟，保持探索节奏快速进入下一轮；
        失败时延迟 4 小时，等待体力回复或人工介入，避免空转。
        :param success: 本轮任务是否成功
        :raises TaskEnd: 抛出以终止当前任务
        """
        delay = timedelta(minutes=5) if success else timedelta(hours=4)
        self.set_next_run(
            task='LevelRush',
            finish=True,
            target=datetime.now() + delay,
        )
        raise TaskEnd('LevelRush')

    def _check_skip_enable(self):
        "检测是否可以直接跳过所有剧情并且到30级"
        get_timer = Timer(5)
        get_timer.start()
        while 1:
            self.screenshot()
            if self.appear(self.I_CHECK_AGREE_DONE):
                self.appear_then_click(self.I_LR_LEVEL_SKIP, interval=1)
                logger.info(f"Skip to 30 level and unlock all chapters success")
                return True
            if self.appear_then_click(self.I_CHECK_AGREE, interval=1):
                get_timer.reset()
                continue
            if self.appear_then_click(self.I_SKIP_TO_30, interval=1):
                get_timer.reset()
                continue
            if get_timer.reached():
                logger.critical(f"Skip exception, request human takeover")
                raise RequestHumanTakeover

    def _get_current_level(self):
        "庭院中获取当前等级"
        if self.get_current_page() != page_main:
            self.goto_page(page_main)
        self.screenshot()
        return self.O_CURRENT_LEVEL.ocr(self.device.image)

    def _get_current_sushi(self):
        "庭院中获取当前体力数量是否不足100，识别标志是否存在‘/’符号"

        if self.get_current_page() != page_main:
            self.goto_page(page_main)

        while 1:
            self.screenshot()
            if self.ocr_appear_click(
                self.O_CLICK_ANYWHERE_CONTINUE, interval=1.2, log=False
            ):
                continue
            if self.appear(GameUiAssets.I_MAIN_GOTO_SHIKIGAMI_RECORDS):
                break
            if not self.appear(GameUiAssets.I_MAIN_GOTO_SHIKIGAMI_RECORDS):
                self.click(RestartAssets.C_LOGIN_SCROLL_CLOSE_AREA, interval=1.2)
                continue

        self.screenshot()
        sushi = self.O_CURRENT_SUSHI_LOW.ocr(self.device.image)
        if sushi and '/' in sushi:
            logger.info(f"当前体力不足100")
            return True
        return False

    def _run_exploration(self):
        "探索循环"
        if not (
            self.config.level_rush.level_rush_config.exploration_chapter_max_15_enable
            and self.config.exploration.exploration_config.exploration_level
            == '第十五章'
        ):
            self.goto_page(page_exploration)
            self.swipe(ExplorationAssets.S_SWIPE_LEVEL_DOWN, interval=1)
            sleep(1)
            cu_chapter = self.O_CURRENT_CHAPTER.ocr(self.device.image)
            level = self._parse_exploration_level(cu_chapter)
            if level is None:
                logger.warning(f'当前章节识别失败: {cu_chapter!r}, 不改配置')
                return

            if level == '第二十八章':
                self.config.level_rush.level_rush_config.skip_to_30_mark = True
                self.config.save()

            # 开启锁定最大章节后，如果超出稳定上限就降级到第十五章
            if level in self._EXPLORATION_CHAPTERS:
                if (
                    self.config.level_rush.level_rush_config.exploration_chapter_max_15_enable
                    and self._EXPLORATION_CHAPTERS.index(level)
                    > self._MAX_CHAPTER_INDEX
                ):
                    logger.info(
                        f'当前章节 {level} 超出稳定上限，降级为 {self._MAX_CHAPTER}'
                    )
                    level = self._MAX_CHAPTER
            else:
                # 识别到了表里没有的章节名，保守按上限处理
                logger.warning(
                    f'章节 {level!r} 不在已知列表，降级为 {self._MAX_CHAPTER}'
                )
                level = self._MAX_CHAPTER
            # 进入当前能进入的最高章节
            while not self.config.level_rush.level_rush_config.skip_to_30_mark:
                self.screenshot()
                if self.appear(self.I_NORMAL_MODE) or self.appear(self.I_HARD_MODE):
                    logger.info(f"进入探索{level}页面")
                    break
                if level is not None:
                    self.appear_then_click(self.I_HIGHEST_CHAPTER, interval=1)
                    continue
            # 切换至困难模式
            while not self.config.level_rush.level_rush_config.skip_to_30_mark:
                self.screenshot()
                if self.appear(self.I_NORMAL_MODE):
                    self.click(self.I_TO_HARD, interval=1)
                    continue
                if self.appear(self.I_HARD_MODE):
                    logger.info(f"Switch to hard mode finish")
                    break
            while level == '第四章':
                self.screenshot()
                if self.appear_then_click(
                    ExplorationAssets.I_E_EXPLORATION_CLICK, interval=1.2
                ):
                    continue
                if self.appear_then_click(self.I_TEAM_UNLOCK, interval=1.2):
                    continue
                if self.appear(self.I_TEAM_LOCKED):
                    logger.info(f"Team locked")
                    break
            # 只覆盖章节，其它参数保持实例里 Exploration 自己的配置
            self.config.script_set_arg(
                task='Exploration',
                group='ExplorationConfig',
                argument='exploration_level',
                value=level,
            )

        # 如果实例里 exploration.scheduler.enable 默认是 false，不打开调度器会直接跳过它
        self.config.script_set_arg(
            task='Exploration',
            group='Scheduler',
            argument='enable',
            value=True,
        )
        # 固定挑战次数为30
        self.config.script_set_arg(
            task='Exploration',
            group='ExplorationConfig',
            argument='minions_cnt',
            value=30,
        )
        # 只打经验buff
        self.config.script_set_arg(
            task='Exploration',
            group='ExplorationConfig',
            argument='up_type',
            value='up_exp',
        )
        # 关闭点击小纸人奖励，防止卡发现妖怪，奖励会自动领取结算
        self.config.script_set_arg(
            task='Exploration',
            group='ExplorationConfig',
            argument='collect_paper_reward',
            value=False,
        )
        self.goto_page(page_main)
        # 3) 唤起：next_run 设为现在，本任务结束后调度器下一轮就挑中 Exploration
        self.config.task_call('Exploration')

    @staticmethod
    def _parse_exploration_level(text: str):
        text = re.sub(r'\s', '', text or '')
        text = text.translate(ScriptTask._OCR_CHAR_FIX)
        m = re.search(
            r'第[一二三四五六七八九十]+章', text
        )  # OCR 就取中文数字，枚举值就是 '第一章'...'第二十八章'
        if not m:
            return None
        try:
            return ExplorationLevel(m.group(0))
        except ValueError:
            return None

    def _get_rookie_reward(self):
        "领取新手活动奖励 此时拥有500体力"
        self.goto_page(page_rookie_act)
        try_count = 0
        while 1:
            sleep(1.2)
            self.screenshot()
            if self.ocr_appear_click(
                self.O_CLICK_ANYWHERE_CONTINUE, interval=1.2, log=False
            ):
                continue
            if self.appear_then_click(self.I_RED_CLOSE, interval=1.2):
                continue
            if self.appear_then_click(
                self.I_RECEIVE_ALL, interval=1.2
            ) or self.appear_then_click(self.I_SIGN_REWARD_DAY1, interval=1.2):
                sleep(1)
                self.click(random_click(ltrb=(False, False, False, True)), interval=1.5)
                logger.info(f"Get reward success")
                continue
            if self.appear_then_click(self.I_TASK_REWARD_EXIST, interval=1.2):
                continue
            if try_count > 3:
                logger.hr(f"Try to get all reward finished")
                break
            if not self.appear(self.I_TASK_REWARD_EXIST):
                try_count += 1
                continue

        self.goto_page(page_main)

    def _run_storyline(self):
        "获取协战之后一路正常推剧情"
        # get_timer = Timer(30)
        # get_timer.start()
        while 1:
            sleep(1.25)
            self.screenshot()
            # 退出标志-剧情锁
            if self.appear(self.I_LEVEL_LOCKED):
                logger.info(f"Storyline locked, try to level up")
                break
            if self.appear_then_click(self.I_PHONE_BIND, interval=1):
                continue
            if self.appear_then_click(self.I_PHONE_BIND_CANCEL, interval=1):
                continue
            if self.get_current_page() == page_exploration:
                self.appear_then_click(self.I_YELLOW_BACK_BUTTON, interval=1)
                continue
            if self.appear_then_click(self.I_TOWN_BACK_MAIN, interval=1):
                continue
            if self.appear(self.I_SKIP_TO_30):
                # 跳过剧情后有绑定手机弹窗 不能直接break
                if self._check_skip_enable():
                    self.config.level_rush.level_rush_config.skip_to_30_mark = True
                    self.config.save()
                    self.stop_flag = True
                continue
            if self.appear_then_click(self.I_RED_CLOSE, interval=1):
                continue
            if self.appear_then_click(self.I_SKIP_TALK, interval=1):
                self.device.click_record_clear()
                continue
            if self.appear_then_click(self.I_OPEN_EYE, interval=1):
                continue
            if self.appear_then_click(self.I_QUESTION_POPUP, interval=1):
                continue
            if self.appear_then_click(self.I_MOVIE_SKIP_CONFIRM, interval=1):
                continue
            if self.appear_then_click(self.I_MOVIE_SKIP, interval=1):
                continue
            if self.appear_then_click(self.I_FIGHT, interval=1) or self.appear(
                self.I_PREPARE_HIGHLIGHT
            ):
                if not self.conf.level_rush_config.assist_up_mark:
                    self._up_assist()
                # 点击但未进入战斗继续循环
                self.screenshot()
                if self.appear(self.I_FIGHT):
                    continue
                self.run_general_battle()
                continue
            if self.appear_then_click(self.I_DOT_DIALOG_POPUP, interval=3):
                self.device.click_record_clear()
                continue
            if self.ocr_appear_click(self.O_CLICK_BLANK_CLOSE, interval=1, log=False):
                continue
            if self.ocr_appear_click(
                self.O_CLICK_ANYWHERE_CONTINUE, interval=1, log=False
            ):
                continue
            # 退出标志-跳过剧情
            if self.config.level_rush.level_rush_config.skip_to_30_mark:
                break

    def _up_assist(self):
        "上阵协战式神"
        while 1:
            self.screenshot()
            if self.appear(self.I_PRESET):
                self.click(self.C_CLICK_UP_ASSIST)
                sleep(1)
                continue
            if self.appear(self.I_ASSIST_UP_SUCCESS):
                self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1)
                self.config.level_rush.level_rush_config.assist_up_mark = True
                self.config.save()
                break
            if self.appear(self.I_SWITCH_CHECK):
                self.swipe(self.S_BORROW_SHIKIGAMI_UP, interval=2)
                continue

    def _run_borrow_gh_bird(self):
        "去借姑获鸟"
        self.goto_page(page_rookie_act)
        while 1:
            sleep(1.2)
            self.screenshot()
            if self.ocr_appear_click(
                self.O_CLICK_ANYWHERE_CONTINUE, interval=1, log=False
            ):
                continue
            if self.appear(self.I_FIRST_BORROW_GET, interval=1):
                self.config.level_rush.level_rush_config.level_7_mark = True
                self.config.save()
                logger.info(f"Success get assist guhuo bired")
                break
            if self.appear_then_click(self.I_GUIDE_FAN, interval=1):
                continue
            if self.appear_then_click(self.I_GH_BIRD_RECOMMEND, interval=1):
                sleep(1.2)
                continue
            if not self.appear(self.I_FIRST_BORROW, interval=1):
                self.ui_click(self.I_ROOKIE_VIP, self.I_IN_ROOKIE_VIP)
                self.ui_click(self.I_BORROW_SHIKIGAMI, self.I_IN_BORROW_SHIKIGAMI)
                continue
        self.goto_page(page_main)

    def _run_before_level_7(self):
        "7级解锁借五星姑获鸟之前的剧情，无法开启自动"
        logger.hr("task before level 7", 2)
        while 1:
            sleep(1.25)
            self.screenshot()
            if self.ui_reward_appear_click():
                continue
            if self.ocr_appear_click(
                self.O_CLICK_ANYWHERE_CONTINUE, interval=1, log=False
            ):
                continue
            if self.appear_then_click(self.I_RED_CLOSE, interval=1):
                continue
            if self.ocr_appear_click(self.O_CLICK_BLANK_CLOSE, interval=1, log=False):
                continue
            if self.appear(self.I_LEVEK_7):
                logger.info(f"Success complete task before level 7")
                break
            if self.appear(self.I_CHECK_AGREE):
                self.ui_click(self.I_CANCEL_BEFORE_7, self.I_UI_CONFIRM)
                self.appear_then_click(self.I_UI_CONFIRM, interval=1)
                continue
            if self.appear_then_click(self.I_CLOSE_RECOMMEND, interval=1):
                continue
            if self.appear(self.I_LR_CHECK_SUMMON):
                self.swipe(self.S_SUMMON_SWIPE, interval=1)
                sleep(2)
                continue
            if self.get_current_page() == page_rookie_act:
                self.goto_page(page_main)
                continue
            if self.appear_then_click(self.I_GUIDE_FAN, interval=1):
                continue
            if self.appear_then_click(self.I_SKIP_TALK, interval=1):
                self.device.click_record_clear()
                continue
            if self.appear_then_click(self.I_SUMMON_CONFIRM, interval=1):
                continue
            if self.appear_then_click(self.I_OPEN_EYE, interval=1):
                continue
            if self.appear_then_click(self.I_QUESTION_POPUP, interval=1):
                continue
            if self.appear_then_click(self.I_MOVIE_SKIP_CONFIRM, interval=1):
                continue
            if self.appear_then_click(self.I_MOVIE_SKIP, interval=1):
                continue
            if self.appear_then_click(self.I_FIGHT, interval=1):
                sleep(2)
                self.ui_click_until_disappear(self.I_PREPARE_HIGHLIGHT)
                continue
            if self.appear(self.I_TECH_LOCK):
                self.click(self.C_NORMAL_ATTACK_CLICK, interval=1)
                continue
            if self.appear_then_click(self.I_CLICK_YOUKAI_1, interval=1):
                continue
            if self.appear_then_click(self.I_CLICK_YOUKAI_2, interval=1):
                continue
            if self.appear(self.I_SWITCH_AUTOMATIC_MARK):
                self.ui_click(self.I_SINGLE_SPEED, self.I_DOUBLE_SPEED)
                self.ui_click(self.I_MANUAL_MODE, self.I_AUTOMATIC_MODE)
                continue
            if self.appear_then_click(self.I_DOGGOD_CLICK, interval=1):
                continue
            if self.appear_then_click(self.I_INIT_PERSPECTIVE, interval=1):
                continue
            if (
                not self.appear(self.I_LR_CHECK_SUMMON)
                and not self.appear(self.I_AUTOMATIC_MODE)
                and not self.appear(self.I_DOUBLE_SPEED)
                and self.appear_then_click(self.I_DOT_DIALOG_POPUP, interval=1)
            ):
                self.device.click_record_clear()
                continue


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
