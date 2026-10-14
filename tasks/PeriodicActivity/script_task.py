# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import random
import re
import time

from cached_property import cached_property

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.ActivityShikigami.page import page_act
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.Delegation.script_task import ScriptTask as DelegationScriptTask
from tasks.DemonEncounter.data.answer import Answer
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.PeriodicActivity.assets import PeriodicActivityAssets
from tasks.PeriodicActivity.config import PeriodicActivity, PeriodicActivityName
from tasks.PeriodicActivity.debug import Debugger, remove_symbols
from tasks.Restart.assets import RestartAssets
import tasks.PeriodicActivity.page as pages

""" 周期活动：灵染试炼 / 智力竞赛 / 呱呱画室 / 青蛙瓷器挑战赛 / 逢魔演武 """


class NoTicket(Exception):
    pass


# 逢魔演武单次运行最多打几场（每日总数 15，留点余量防止识别失灵时死循环）
DRILL_MAX_BATTLES = 20


# 基类顺序有讲究：`DelegationScriptTask` 自身继承 `GameUi`，它必须排在 `GameUi` 前面，
# 否则 C3 会成环（GameUi < SwitchSoul < DelegationScriptTask < GameUi）直接 TypeError。
class ScriptTask(GeneralBattle, DelegationScriptTask, GameUi, SwitchSoul,
                 PeriodicActivityAssets, Debugger):
    """ 周期活动 """

    # ---------------------------- 逢魔演武 ----------------------------

    # 连续识别不到剩余次数时的退出保护（避免识别失败后无脑点挑战）
    dd_ocr_fail_limit = 3

    def run_demon_drill(self) -> bool:
        """逢魔演武：庭院右侧活动栏 →（勾选时先做逢魔委派）→ 演武挑战 → 挑战 → 打到没次数。

        用到的 image 规则：`I_DRILL_ENTRY`（庭院活动栏入口）、`I_DRILL_CHECK`（逢魔演武界面标志）、
        `I_DRILL_CHALLENGE`（演武挑战）、`I_DRILL_FIRE`（挑战）。

        Returns:
            bool: True 表示挑战跑完（含已经没有次数）；False 表示入口/按钮没认出来（按失败间隔重试）
        """
        logger.hr('Demon drill', level=1)
        self.goto_page(page_main)

        if not self.enter_drill_activity():
            return False

        # 勾选了「是否执行逢魔委派」就先做委派，完成后再回来打演武
        if self.conf.periodic_activity_config.demon_drill_delegation_enable:
            if not self.run_drill_delegation():
                logger.warning('Demon drill delegation failed, go back to the drill')
            # 委派可能已经把界面带到式神委派页，无论成败都先回到演武界面
            if not self.back_to_drill_page():
                return False

        if not self.wait_until_appear(self.I_DRILL_CHALLENGE, wait_time=10):
            logger.warning('Demon drill activity page not detected after entering')
            return False
        self.appear_then_click(self.I_DRILL_CHALLENGE, interval=1)

        battles = 0
        ocr_fail_count = 0
        while battles < DRILL_MAX_BATTLES:
            if not self.wait_until_appear(self.I_DRILL_FIRE, wait_time=10):
                if battles == 0:
                    # 一场都没打起来：入口/按钮没认出来，按失败间隔重试
                    logger.warning('Demon drill challenge button not detected')
                    return False
                logger.warning('Demon drill challenge button not detected, stop here')
                break
            remain = self.read_drill_remain()
            if remain is None:
                # 读不到次数时不保守跳过（免得漏打），但连续读不到就收手
                ocr_fail_count += 1
                logger.warning(f'Cannot read remaining count '
                               f'[{ocr_fail_count}/{self.dd_ocr_fail_limit}]')
                if ocr_fail_count >= self.dd_ocr_fail_limit:
                    logger.warning('Remaining count unrecognizable, stop here')
                    break
            else:
                ocr_fail_count = 0
                logger.info(f'Demon drill remaining: {remain}')
                if remain <= 0:
                    logger.info('Demon drill: no challenge left, stop here')
                    break
            self.appear_then_click(self.I_DRILL_FIRE, interval=1.2)
            self.run_general_battle(config=self.conf.general_battle_config,
                                    exit_matcher=self.I_DRILL_FIRE,
                                    battle_key='demon_drill')
            battles += 1
            self.device.stuck_record_clear()

        self.goto_page(page_main)
        logger.info(f'Demon drill done, battles={battles}')
        return True

    def read_drill_remain(self) -> int or None:
        """读「剩余次数x/15」里的 x（剩余次数）。

        Returns:
            int: 剩余次数；没识别到返回 None（调用方按连续失败次数收手）
        """
        text = str(self.O_DRILL_REMAIN.ocr(self.device.image) or '')
        # OCR 可能给出全角字符，先归一化再解析
        text = text.translate(str.maketrans('０１２３４５６７８９／', '0123456789/'))
        match = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if not match:
            logger.warning(f'Demon drill: cannot read remaining count from {text!r}')
            return None
        return int(match.group(1))

    def enter_drill_activity(self) -> bool:
        """庭院右侧活动栏 → 进入逢魔演武活动页，并 check 是否在逢魔演武界面。

        Returns:
            bool: 进入且确认在逢魔演武界面返回 True
        """
        if not self.find_drill_entry():
            logger.warning('Demon drill entry not found in the right activity bar')
            return False
        self.appear_then_click(self.I_DRILL_ENTRY, interval=1)
        if not self.wait_until_appear(self.I_DRILL_CHECK, wait_time=10):
            logger.warning('Not on the demon drill page after entering the activity')
            return False
        return True

    def run_drill_delegation(self) -> bool:
        """逢魔委派：逢魔演武页 →「前往演武委派」→ 式神委派界面点右侧「演武委派」。

        委派本身与普通式神委派共用一套流程（复用式神委派任务的 check_reward /
        delegate_one），只是列表里的条目用 image 规则 `I_DRILL_DELEGATION` 定位。

        Returns:
            bool: 委派发起成功返回 True
        """
        logger.hr('Demon drill delegation', level=1)
        self.screenshot()
        if not self.appear(self.I_DRILL_CHECK):
            logger.warning('Demon drill delegation: not on the demon drill page')
            return False
        # 前往演武委派 → 式神委派界面（check 复用现有资源 I_CHECK_DELEGATION）
        if not self.ui_click_until_appear_or_timeout(self.I_GOTO_DRILL_DELEGATION,
                                                    stop=self.I_CHECK_DELEGATION,
                                                    interval=1.5, timeout=15):
            logger.warning('Demon drill delegation: shikigami delegation page not reached')
            return False
        # 先领掉已完成的委派奖励，再发起「演武委派」
        self.check_reward()
        if not self.delegate_one('演武委派', entry=self.I_DRILL_DELEGATION):
            logger.warning('Demon drill delegation: delegate 演武委派 failed')
            return False
        logger.info('Demon drill delegation done')
        return True

    def back_to_drill_page(self) -> bool:
        """从式神委派界面回到逢魔演武界面。

        式神委派的返回键是回探索页（页面图里 `page_delegation` 的出边就是回探索），
        所以直接回庭院再进一次活动页。

        Returns:
            bool: 回到逢魔演武界面返回 True
        """
        self.goto_page(page_main)
        return self.enter_drill_activity()

    def find_drill_entry(self) -> bool:
        """在庭院右侧活动栏里找「逢魔演武」入口，最多切换八轮栏目。

        Returns:
            bool: 入口出现在画面上返回 True；不在庭院、或八轮都没找到返回 False
        """
        for _ in range(8):
            self.screenshot()
            if not self.appear(self.I_CHECK_MAIN):
                logger.warning('Demon drill entry search: not on the main page')
                return False
            if self.appear(self.I_DRILL_ENTRY):
                logger.info('Demon drill entry found')
                return True
            if self.appear_then_click(RightActivityAssets.I_TOGGLE_BUTTON, interval=1):
                time.sleep(1)      # 等栏目切换动画
                continue
            time.sleep(0.5)
        self.screenshot()
        return self.appear(self.I_DRILL_ENTRY)

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
        success = True
        match activity:
            case PeriodicActivityName.DYE_TRIALS:
                self.run_dye_trials()
            case PeriodicActivityName.QUIZ:
                self.run_quiz()
            case PeriodicActivityName.GUGU_ART_STUDIO:
                self.run_gugu_art_studio()
            case PeriodicActivityName.FROG_CHALLENGE:
                # 异常退出时按失败间隔重试，其余子活动保持原行为
                success = self.run_frog_challenge()
            case PeriodicActivityName.DEMON_DRILL:
                success = self.run_demon_drill()
            case _:
                logger.error(f'Unknown periodic activity: {activity}')

        self.set_next_run(task='PeriodicActivity', success=success, finish=True)
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

    # ---------------------------- 青蛙瓷器挑战赛 ----------------------------

    # 连续识别不到骰子奖励进度时的退出保护（避免识别失败后无脑点挑战）
    fc_ocr_fail_limit = 3
    # 连续挑战但奖励进度不涨时的退出保护（避免挑战点不中时空转）
    fc_no_progress_limit = 3

    def run_frog_challenge(self) -> bool:
        """青蛙瓷器挑战赛

        挑战次数上限以「神秘骰子奖励进度」实时识别为准：进度形如 25/50，
        左边是今日已获取的骰子、右边是今日可获取的总量；每次挑战 25 个，
        奖励最多累计 3 天（右值会变成 50/100/150），所以不写死次数。
        本活动没有锁定阵容功能，直接由通用战斗点准备进战斗。

        Returns:
            bool: True 表示今日奖励刷满（或无奖励可打）；False 表示识别/挑战异常提前退出
        """
        logger.hr('Frog challenge', level=1)
        self.switch_soul_by_config()
        # 点击庭院右侧图标直接进入挑战页面，没有中间页面
        self.goto_page(pages.page_frog_challenge)
        battle_count = 0
        ocr_fail_count = 0
        no_progress_count = 0
        last_acquired = -1
        result = True
        while True:
            self.screenshot()
            # 首次进入的剧情：跳过
            if self.appear_then_click(self.I_FC_SKIP, interval=0.8):
                logger.info('Skip story')
                continue
            if self.get_current_page() == pages.page_frog_challenge:
                # 战斗按钮变成「无奖励」状态：今日没奖励了，收工
                if self.appear(self.I_FC_FIRE_STOP):
                    logger.info('No reward battle left, exit')
                    break
                # 今日已经获取 / 今日可以获取
                acquired, remain, total = self.O_MYSTERY_DICE_REWARD.ocr(self.device.image)
                if total <= 0:
                    ocr_fail_count += 1
                    logger.warning(
                        f'Cannot read dice reward [{ocr_fail_count}/{self.fc_ocr_fail_limit}]'
                    )
                    if ocr_fail_count >= self.fc_ocr_fail_limit:
                        logger.warning('Dice reward unrecognizable, exit')
                        result = False
                        break
                    time.sleep(0.5)
                    continue
                ocr_fail_count = 0
                logger.info(f'Dice reward today {acquired}/{total}, remain {remain}')
                if acquired >= total:
                    logger.info('Today reward reached, exit')
                    break
                # 上一轮挑战没有让进度涨，说明挑战没打起来
                if last_acquired >= 0 and acquired <= last_acquired:
                    no_progress_count += 1
                    logger.warning(
                        f'Reward progress not increased '
                        f'[{no_progress_count}/{self.fc_no_progress_limit}]'
                    )
                    if no_progress_count >= self.fc_no_progress_limit:
                        logger.warning('Cannot start challenge, exit')
                        result = False
                        break
                else:
                    no_progress_count = 0
                last_acquired = acquired
                # 挑战
                if self.appear_then_click(self.I_FC_FIRE, interval=1.2):
                    logger.info(f'Battle [{battle_count + 1}], reward {acquired}/{total}')
                    time.sleep(0.5)
                    if self.appear(self.O_CLICK_ANYWHERE_CONTINUE, interval=1):
                        random_click(ltrb=(True, False, False, False))
                    self.run_general_battle(config=self.conf.general_battle_config,
                                            exit_matcher=pages.page_frog_challenge)
                    battle_count += 1
                    self.device.stuck_record_clear()
                    continue
            time.sleep(0.2)
        logger.info(f'Frog challenge done, battles={battle_count}, result={result}')
        self.goto_page(page_main)
        return result

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
        """切换御魂（灵染试炼、呱呱画室、青蛙瓷器挑战赛共用）"""
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
