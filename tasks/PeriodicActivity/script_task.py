# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import random
import time

from cached_property import cached_property

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.ActivityShikigami.page import page_act
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.DemonEncounter.data.answer import Answer
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.PeriodicActivity.assets import PeriodicActivityAssets
from tasks.PeriodicActivity.config import PeriodicActivity, PeriodicActivityName
from tasks.PeriodicActivity.debug import Debugger, remove_symbols
from tasks.Restart.assets import RestartAssets
import tasks.PeriodicActivity.page as pages

""" 周期活动：灵染试炼 / 智力竞赛 / 呱呱画室 """


class NoTicket(Exception):
    pass


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, PeriodicActivityAssets, Debugger):
    """ 周期活动 """

    # ---------------------------- 智力竞赛 ----------------------------
    answer_cnt = 0
    last_select_1 = ''
    last_select_2 = ''
    last_select_3 = ''
    last_select_4 = ''
    # 添加倒计时状态变量
    last_countdown = None
    runalone = False

    # ---------------------------- 呱呱画室 ----------------------------
    conf: PeriodicActivity = None

    def run(self) -> None:
        self.conf = self.config.periodic_activity
        activity = self.conf.periodic_activity_config.activity
        logger.hr(f'Periodic activity: {activity.value}')
        match activity:
            case PeriodicActivityName.DYE_TRIALS:
                self.run_dye_trials()
            case PeriodicActivityName.QUIZ:
                self.run_quiz()
            case PeriodicActivityName.GUGU_ART_STUDIO:
                self.run_gugu_art_studio()
            case _:
                logger.error(f'Unknown periodic activity: {activity}')

        self.set_next_run(task='PeriodicActivity', success=True, finish=True)
        raise TaskEnd('PeriodicActivity')

    # ---------------------------- 灵染试炼 ----------------------------

    def run_dye_trials(self) -> None:
        logger.hr('Dye trials', level=1)
        self.switch_soul_by_config()
        self.goto_page(page_main)
        self.get_all()
        self.goto_page(page_main)

    def get_all(self) -> None:
        while 1:
            self.screenshot()
            if self.appear(self.I_FP_CHALLENGE):
                break
            if self.appear_then_click(self.I_FP_ACCESS, interval=0.8):
                continue
            if self.appear_then_click(self.I_FP_ACCESS_1, interval=1.5):
                continue
            if self.appear_then_click(self.I_TOGGLE_BUTTON, interval=3):
                continue
        logger.info('Enter DyeTrials')
        boss_timer = Timer(60)
        boss_timer.start()
        battle_num = 0
        while 1:
            self.screenshot()
            time.sleep(0.1)
            if boss_timer.reached():
                self.config.notifier.push(title='超鬼王', message='识别超时退出')
                break
            # 关闭获得皮肤提示弹窗
            if self.appear_then_click(self.I_FP_CLOSE_GET_SKIN, interval=0.8):
                logger.warning('Maybe already get skin, close tip')
                continue
            # 获得奖励
            if self.ui_reward_appear_click():
                boss_timer.reset()
            if self.appear_then_click(RestartAssets.I_HARVEST_CHAT_CLOSE):
                boss_timer.reset()
                continue
            if self.appear(self.I_FP_CHALLENGE, interval=1):
                cu, res, total = self.O_BATTLE_NUM.ocr(image=self.device.image)
                if cu == total == 50 and cu + res == total:
                    break
                if battle_num >= 50:
                    logger.info(f'Battle {battle_num}, enough battle, break')
                    break
                self.ui_click_until_disappear(self.I_FP_CHALLENGE)
                battle_num += 1
                logger.info(f'Battle num [{battle_num}]')
                self.device.stuck_record_clear()
                self.device.stuck_record_add('BATTLE_STATUS_S')
                boss_timer.reset()
                continue
            if self.appear_then_click(self.I_BATTLE_SUCCESS, interval=1):
                boss_timer.reset()
                continue

    # ---------------------------- 呱呱画室 ----------------------------

    def run_gugu_art_studio(self) -> None:
        logger.hr('Gugu art studio', level=1)
        self.switch_soul_by_config()
        self.goto_page(pages.page_gugu_fire)
        unknown_page_seconds = 8
        unknown_page_timer = Timer(unknown_page_seconds)
        max_submit = random.randint(2, 3)
        while True:
            self.screenshot()
            if max_submit <= 0:
                logger.info('Submit paint success, exit')
                break
            current_page = self.get_current_page()
            match current_page:
                case None:
                    time.sleep(0.5)
                case pages.page_gugu:
                    unknown_page_timer = Timer(unknown_page_seconds)
                    if self.appear_then_click(self.I_SUBMIT_PAINT, interval=0.8):
                        max_submit -= 1
                        self.get_reward()
                case pages.page_gugu_fire:
                    unknown_page_timer = Timer(unknown_page_seconds)
                    if self.appear_then_click(self.I_GOTO_SUBMIT):
                        logger.info('Get paint finish, go to submit paint')
                        continue
                    if self.appear(self.I_GAS_CANNOT_FIRE):  # 无法挑战则退出到提交颜料页面
                        logger.info('Cannot fire, go to submit paint')
                        self.goto_page(pages.page_gugu)
                        continue
                    self.switch_lock()
                    if self.appear_then_click(self.I_GAS_CAN_FIRE, interval=1.2):  # 点击挑战
                        self.run_general_battle(config=self.conf.general_battle_config,
                                                exit_matcher=pages.page_gugu_fire)
                case _:
                    if not unknown_page_timer.started():
                        unknown_page_timer.start()
                    if unknown_page_timer.reached():
                        self.goto_page(pages.page_gugu_fire)
                        unknown_page_timer = Timer(unknown_page_seconds)
        self.goto_page(pages.page_main)

    def switch_lock(self) -> None:
        if self.conf.general_battle_config.lock_team_enable:
            self.ui_click(self.I_GAS_UNLOCK, self.I_GAS_LOCK)
            return
        self.ui_click(self.I_GAS_LOCK, self.I_GAS_UNLOCK)

    def get_reward(self) -> None:
        logger.hr('Get gugu reward', 3)
        reward_click = [self.C_GAS_REWARD_1, self.C_GAS_REWARD_2, self.C_GAS_REWARD_3, self.C_GAS_REWARD_4,
                        self.C_GAS_REWARD_5]
        for click in reward_click:
            self.I_GAS_REWARD_LOCK.roi_back = click.roi_back
            self.I_GAS_ALREADY_GET_REWARD.roi_back = click.roi_back
            self.screenshot()
            if self.appear(self.I_GAS_REWARD_LOCK):
                logger.info(f'Skip {click.name} on lock')
                break
            if self.appear(self.I_GAS_ALREADY_GET_REWARD):
                logger.info(f'Skip {click.name} on already get')
                continue
            logger.info(f'Get {click.name}')
            self.ui_get_reward(click, click_interval=2.5)
            break
        logger.info('Get gugu reward done')

    # ---------------------------- 智力竞赛 ----------------------------

    @cached_property
    def anwser(self) -> Answer:
        # Misspelling
        return Answer()

    @cached_property
    def click_options(self) -> list:
        return [self.O_ANSWER1, self.O_ANSWER2, self.O_ANSWER3, self.O_ANSWER4]

    @cached_property
    def _config(self):
        return self.config.model.periodic_activity.quiz_config

    def run_quiz(self) -> None:
        logger.hr('Quiz', level=1)
        self.goto_page(page_main)
        _config = self.config.model.periodic_activity.quiz_config
        self.enter()

        quiz_cnt = 0
        while 1:
            if quiz_cnt >= _config.quiz_cnt:
                break
            try:
                self.once()
                quiz_cnt += 1
            except NoTicket:
                break

        self.ui_click(self.I_UI_BACK_YELLOW, self.I_CHECK_MAIN, interval=2)

    def enter(self):
        self.goto_page(page_act)
        while True:
            self.screenshot()
            if self.appear(self.I_START):
                break
            if self.appear_then_click(self.I_ENTRY, interval=1):
                continue
        logger.info('Quiz start')

    def once(self) -> bool:
        logger.hr('Quiz', 3)
        start_cnt = 0
        self.answer_cnt = 0
        # 重置倒计时状态
        self.last_countdown = None
        while 1:
            self.screenshot()
            if self.appear(self.I_MESSAGE):
                break
            if start_cnt >= 4:
                logger.error('No ticket')
                raise NoTicket('No ticket')
            if self.appear_then_click(self.I_START, interval=1.5):
                start_cnt += 1
                continue
        self.last_select_1, self.last_select_2, self.last_select_3, self.last_select_4 = '', '', '', ''

        quiz_timer = Timer(1.4)
        quiz_timer.start()
        while 1:
            self.screenshot()

            if self.ui_reward_appear_click():
                continue
            if self.appear(self.I_FAIL_QUIT):
                # 失败
                logger.info('Quiz Fail and exit')
                self.ui_click(self.I_FAIL_QUIT, self.I_START)
                break
            if self.appear(self.I_SHARE):
                # 结算
                logger.info('Quiz Victory and exit')
                self.ui_click(self.I_UI_BACK_RED, self.I_START)
                break
            if quiz_timer.reached():
                quiz_timer.reset()
                self._deal_quiz()
                continue
        self.close_fn()

    def detect_new(self, select_1, select_2, select_3, select_4) -> bool:
        # 计算不同答案的数量
        diff_count = 0
        if self.last_select_1 != select_1:
            diff_count += 1
        if self.last_select_2 != select_2:
            diff_count += 1
        if self.last_select_3 != select_3:
            diff_count += 1
        if self.last_select_4 != select_4:
            diff_count += 1

        # 如果有3个或以上答案不同，则认为是新问题
        new = diff_count >= 3

        self.last_select_1, self.last_select_2, self.last_select_3, self.last_select_4 = \
            select_1, select_2, select_3, select_4
        return new

    def _deal_quiz(self):
        countdown = self.O_COUNTDOWN.ocr(self.device.image)

        """  # 检查倒计时状态变化：从大于0变为0时进入下一题
        if self.last_countdown is not None and self.last_countdown > 0 and countdown == 0:
            logger.info("Countdown changed from greater than 0 to 0, moving to next question")
            return False

        self.last_countdown = countdown """

        if countdown < 2 or countdown > 5:
            # 最后两秒钟的时候 进行选择
            if countdown > 100:
                self.runalone = True
            else:
                return False

        question, answer_1, answer_2, answer_3, answer_4 = self.detect_question_and_answers()
        if answer_1 == '' and answer_2 == '' and answer_3 == '' and answer_4 == '':
            return False
        question = remove_symbols(question)

        new_question = self.detect_new(answer_1, answer_2, answer_3, answer_4)
        if not new_question:
            if self.runalone:
                self.appear_then_click(self.I_ALONE_ENSURE, interval=1)
                pass
            return False
        self.answer_cnt += 1
        logger.info(f'Question count: {self.answer_cnt}')

        index = self.anwser.answer_one(question=question, options=[answer_1, answer_2, answer_3, answer_4])
        if index is None:
            logger.error('Now question has no answer, please check')
            self.append_one(question=question, options=[answer_1, answer_2, answer_3, answer_4])
            self.config.notifier.push(title='Quiz',
                                      content=f"New question: \n{question} \n{[answer_1, answer_2, answer_3, answer_4]}")
            index = 1

        if self._config.quiz_per_round < 150 and self.answer_cnt > self._config.quiz_per_round:
            index_options = {1, 2, 3, 4}
            index_options.remove(index)
            index = random.choice(list(index_options))
        logger.attr(index, 'Answer')
        self.click(self.click_options[index - 1], interval=1)
        time.sleep(0.5)
        if index == 1:
            self.click(self.C_ANSWER_ENSURE_1)
        if index == 2:
            self.click(self.C_ANSWER_ENSURE_2)
        if index == 3:
            self.click(self.C_ANSWER_ENSURE_3)
        if index == 4:
            self.click(self.C_ANSWER_ENSURE_4)
        self.device.click_record_clear()
        return True

    def detect_question_and_answers(self) -> tuple:
        results = self.O_QUESTION.detect_and_ocr(self.device.image)
        question = ''
        answer_1 = remove_symbols(self.O_ANSWER1.ocr(self.device.image))
        answer_2 = remove_symbols(self.O_ANSWER2.ocr(self.device.image))
        answer_3 = remove_symbols(self.O_ANSWER3.ocr(self.device.image))
        answer_4 = remove_symbols(self.O_ANSWER4.ocr(self.device.image))

        for result in results:
            # box 是四个点坐标 左上， 右上， 右下， 左下
            # x1, y1, x2, y2 = result.box[0][0], result.box[0][1], result.box[2][0], result.box[2][1]
            # w, h = x2 - x1, y2 - y1
            y_start = result.box[0][1]
            y_end = result.box[2][1]
            text = result.ocr_text
            if y_start >= 0 and y_end <= 150:
                question += text

        return question, answer_1, answer_2, answer_3, answer_4

    # ---------------------------- 公共 ----------------------------

    def switch_soul_by_config(self) -> None:
        """切换御魂（灵染试炼、呱呱画室共用）"""
        cfg = self.conf.switch_soul_config
        if cfg.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(cfg.switch_group_team)
        if cfg.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(cfg.group_name, cfg.team_name)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
