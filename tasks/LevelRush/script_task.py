import re

from datetime import datetime, timedelta
from time import sleep

from module.base.timer import Timer
from module.logger import logger
from module.exception import TaskEnd
from tasks.EvoZone.config import Layer, KirinType
from tasks.EvoZone.script_task import ScriptTask as EvoZoneScriptTask
from tasks.GameUi.default_pages import random_click
from tasks.RealmRaid.script_task import ScriptTask as RealmRaidScriptTask
from tasks.DailyTrifles.script_task import ScriptTask as DailyTriflesScriptTask
from tasks.GameUi.page import page_main, page_exploration, page_team
from tasks.Exploration.page import page_exp_entrance
from tasks.Exploration.config import ExplorationLevel
from tasks.Exploration.assets import ExplorationAssets
from tasks.LevelRush.assets import LevelRushAssets
from tasks.LevelRush.config import LevelRushConfig


class ScriptTask(
    EvoZoneScriptTask,
    RealmRaidScriptTask,
    DailyTriflesScriptTask,
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
    conf: LevelRushConfig

    def run(self):
        self.conf = self.config.model.level_rush
        if self.conf.level_rush_config.random_name_enable:
            self._run_before_level_0()
        if not self.conf.level_rush_config.level_7_mark:
            self._run_before_level_7()
            self._run_borrow_gh_bird()
            self.run_pickup_email()
            self._get_rookie_reward()
        self._run_storyline()
        if self._get_current_level() >= 45:
            # 达到目标等级后本任务不再需要，把自己在实例配置里禁用，当作一次性任务
            self.config.level_rush.scheduler.enable = False
            self.config.level_rush.level_rush_config.level_7_mark = False
            self.config.level_rush.level_rush_config.assist_up_mark = False
            self.config.save()
            self.set_next_run(task='LevelRush', success=True, finish=True)
            raise TaskEnd('LevelRush')
        if not self._get_current_sushi():
            self._run_exploration()
        else:
            # 体力不足
            self.set_next_run(task='LevelRush', success=False, finish=True)
            raise TaskEnd('LevelRush')
        self.set_next_run(task='LevelRush', success=True, finish=True)
        raise TaskEnd('LevelRush')

    def _get_current_level(self):
        "庭院中获取当前等级"
        if self.get_current_page() != page_main:
            self.goto_page(page_main)
        return self.O_CURRENT_LEVEL.ocr(self.device.image)

    def _get_current_sushi(self):
        "庭院中获取当前体力数量是否不足100"
        if self.get_current_page() != page_main:
            self.goto_page(page_main)
        if self.ocr_appear(self.O_CURRENT_SUSHI_LOW, interval=1):
            return True
        return False

    def _run_exploration(self):
        "探索循环"
        self.goto_page(page_exploration)
        self.swipe(ExplorationAssets.S_SWIPE_LEVEL_DOWN, interval=1)
        sleep(1)
        cu_chapter = self.O_CURRENT_CHAPTER.ocr(self.device.image)
        level = self._parse_exploration_level(cu_chapter)
        if level is None:
            logger.warning(f'当前章节识别失败: {cu_chapter!r}, 不改配置')
            return

        # 1) 只覆盖章节，其它参数保持实例里 Exploration 自己的配置
        self.config.script_set_arg(
            task='Exploration',
            group='ExplorationConfig',
            argument='exploration_level',
            value=level,
        )
        # 2) 实例里 exploration.scheduler.enable 默认是 false，不打开调度器会直接跳过它
        self.config.script_set_arg(
            task='Exploration',
            group='Scheduler',
            argument='enable',
            value=True,
        )
        while 1:
            self.screenshot()
            if self.appear(self.I_NORMAL_MODE) or self.appear(self.I_HARD_MODE):
                break
            if level is not None:
                self.appear_then_click(self.I_HIGHEST_CHAPTER, interval=1)
                continue

        while 1:
            self.screenshot()
            if self.appear(self.I_NORMAL_MODE):
                self.click(self.I_TO_HARD, interval=1)
                continue
            if self.appear(self.I_HARD_MODE):
                break

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
        "领取新手活动奖励"
        self.ui_click(self.I_GOTO_ROOKIE_ACT, self.I_CHECK_ROOKIE_ACT)
        while 1:
            self.screenshot()
            if self.ocr_appear_click(self.O_CLICK_ANYWHERE_CONTINUE, interval=1):
                continue
            if self.appear_then_click(self.I_START_ROAD, interval=1):
                continue
            if self.appear_then_click(self.I_RED_CLOSE, interval=1):
                continue
            if self.appear_then_click(self.I_RECEIVE_ALL, interval=1):
                sleep(2)
                self.click(random_click(ltrb=(True, False, False, False)), interval=1.5)
                logger.info("get reward of start road")
                continue
            if self.appear_then_click(self.I_TASK_REWARD_EXIST, interval=1):
                continue
            if self.appear(self.I_IN_START_ROAD, interval=1) and not self.appear(
                self.I_TASK_REWARD_EXIST, interval=1
            ):
                break
        self.screenshot()
        self.appear_then_click(self.I_YELLOW_BACK_BUTTON, interval=1)
        logger.info("back to main")

    def _run_storyline(self):
        "获取协战之后一路正常推剧情"
        while 1:
            sleep(1)
            self.screenshot()
            if self.appear(self.I_LEVEL_LOCKED):
                break
            if self.get_current_page() == page_exploration:
                self.goto_page(page_main)
                continue
            if self.appear_then_click(self.I_PHONE_BIND, interval=1):
                continue
            if self.appear_then_click(self.I_PHONE_BIND_CANCEL, interval=1):
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
                self.run_general_battle()
                continue
            if self.appear_then_click(self.I_DOT_DIALOG_POPUP, interval=3):
                self.device.click_record_clear()
                continue
            if self.ocr_appear_click(self.O_CLICK_BLANK_CLOSE, interval=1):
                continue
            if self.ocr_appear_click(self.O_CLICK_ANYWHERE_CONTINUE, interval=1):
                continue

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
        self.ui_click(self.I_GOTO_ROOKIE_ACT, self.I_CHECK_ROOKIE_ACT)
        while 1:
            self.screenshot()
            if self.appear(self.I_FIRST_BORROW_GET, interval=1):
                self.config.level_rush.level_rush_config.level_7_mark = True
                self.config.save()
                logger.info("success get assist guhuo bired")
                break
            if self.appear_then_click(self.I_GUIDE_FAN, interval=1):
                continue
            if self.appear_then_click(self.I_GH_BIRD_RECOMMEND, interval=1):
                continue
            if not self.appear(self.I_FIRST_BORROW, interval=1):
                self.ui_click(self.I_ROOKIE_VIP, self.I_IN_ROOKIE_VIP)
                self.ui_click(self.I_BORROW_SHIKIGAMI, self.I_IN_BORROW_SHIKIGAMI)
                continue
        self.screenshot()
        self.appear_then_click(self.I_YELLOW_BACK_BUTTON, interval=1)
        logger.info("back to main")

    def _run_before_level_0(self):
        "自动注册角色"
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_ROLL_NAME):
                continue
            if not self.O_NAME_CHECK.ocr(self.device.image):
                self.appear_then_click(self.I_CREATE_PLAYER)
                pass
            if self.appear(self.I_DOT_DIALOG_POPUP):
                break

    def _run_before_level_7(self):
        "7级解锁借五星姑获鸟之前的剧情，无法开启自动"

        while 1:
            sleep(2)
            self.screenshot()
            if self.appear_then_click(self.I_RED_CLOSE, interval=1):
                continue
            if self.ocr_appear_click(self.O_CLICK_BLANK_CLOSE, interval=1):
                continue
            if self.appear(self.I_LEVEK_7):
                break
            if self.O_CURRENT_LEVEL.ocr(self.device.image) >= 7:
                break
            if self.appear_then_click(self.I_CLOSE_RECOMMEND, interval=1):
                continue
            if self.appear(self.I_LR_CHECK_SUMMON):
                self.swipe(self.S_SUMMON_SWIPE, interval=1)
                sleep(2)
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
                continue
            if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1):
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
            if self.appear_then_click(self.I_INIT_PERSPECTIVE, interval=1):
                continue
            if (
                not self.appear(self.I_LR_CHECK_SUMMON)
                and not self.appear(self.I_AUTOMATIC_MODE)
                and not self.appear(self.I_DOUBLE_SPEED)
                and self.appear_then_click(self.I_DOT_DIALOG_POPUP, interval=3)
            ):
                self.device.click_record_clear()
                continue
            if self.ocr_appear_click(self.O_BATTLE_FINISH, interval=1):
                continue
            if self.ocr_appear_click(self.O_CLICK_ANYWHERE_CONTINUE, interval=1):
                continue


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
