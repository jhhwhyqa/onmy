# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import re
import time

from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Delegation.script_task import ScriptTask as DelegationScriptTask
from tasks.DemonDrill.assets import DemonDrillAssets
from tasks.DemonDrill.config import DemonDrill
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
import tasks.DemonDrill.page as pages
from tasks.Component.RightActivity.assets import RightActivityAssets
from module.base.timer import Timer


# 逢魔演武单次运行最多打几场（每日总数 15，留点余量防止识别失灵时死循环）
DRILL_MAX_BATTLES = 20


# 基类顺序有讲究：`DelegationScriptTask` 自身继承 `GameUi`，它必须排在 `GameUi` 前面，
# 否则 C3 会成环（GameUi < GeneralBattle < DelegationScriptTask < GameUi）直接 TypeError。
class ScriptTask(GeneralBattle, DelegationScriptTask, GameUi, DemonDrillAssets):
    """逢魔演武"""

    conf: DemonDrill = None

    # 连续识别不到剩余次数时的退出保护（避免识别失败后无脑点挑战）
    dd_ocr_fail_limit = 3

    def run(self) -> None:
        self.conf = self.config.demon_drill_config
        success = self.run_demon_drill()
        self.set_next_run(task='DemonDrill', success=success, finish=True)
        raise TaskEnd('DemonDrill')

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
        if self.conf.demon_drill_delegation_enable:
            # 检查当前是否正在委派中
            if self.check_delegation_in_progress():
                logger.info('Demon drill delegation already in progress, skip delegation')
            else:
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

    def check_delegation_in_progress(self) -> bool:
        """检查当前逢魔委派是否正在进行中。

        在逢魔演武界面通过 OCR 识别「委派中」文字判断。

        Returns:
            bool: 正在委派中返回 True，否则返回 False
        """
        self.screenshot()
        if not self.appear(self.I_DRILL_CHECK):
            logger.warning('Not on demon drill page when checking delegation status')
            return False

        result = self.O_DRILL_DELEGATION_STATUS.ocr(self.device.image)
        if result and '委派中' in str(result):
            logger.info('Demon drill delegation is already in progress')
            return True
        return False

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
