# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.FrogChallenge.assets import FrogChallengeAssets
from tasks.FrogChallenge.config import FrogChallenge
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records
import tasks.FrogChallenge.page as pages


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, FrogChallengeAssets):
    """青蛙瓷器"""

    conf: FrogChallenge = None

    # 连续识别不到骰子奖励进度时的退出保护（避免识别失败后无脑点挑战）
    fc_ocr_fail_limit = 3
    # 连续挑战但奖励进度不涨时的退出保护（避免挑战点不中时空转）
    fc_no_progress_limit = 3

    def run(self) -> None:
        self.conf = self.config.frog_challenge
        success = self.run_frog_challenge()
        self.set_next_run(task='FrogChallenge', success=success, finish=True)
        raise TaskEnd('FrogChallenge')

    def run_frog_challenge(self) -> bool:
        """青蛙瓷器

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

    def switch_soul_by_config(self) -> None:
        """切换御魂"""
        cfg = self.conf.switch_soul_config
        if cfg.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(cfg.switch_group_team)
        if cfg.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(cfg.group_name, cfg.team_name)
