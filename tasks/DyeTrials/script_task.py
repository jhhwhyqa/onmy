# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.DyeTrials.assets import DyeTrialsAssets
from tasks.DyeTrials.config import DyeTrials
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.Restart.assets import RestartAssets


class ScriptTask(GameUi, SwitchSoul, DyeTrialsAssets):
    """灵染试炼"""

    conf: DyeTrials = None

    def run(self) -> None:
        self.conf = self.config.dye_trials
        logger.hr('Dye trials', level=1)
        self.switch_soul_by_config()
        self.goto_page(page_main)
        self.get_all()
        self.goto_page(page_main)

        self.set_next_run(task='DyeTrials', success=True, finish=True)
        raise TaskEnd('DyeTrials')

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

    def switch_soul_by_config(self) -> None:
        """切换御魂"""
        cfg = self.conf.switch_soul_config
        if cfg.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(cfg.switch_group_team)
        if cfg.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(cfg.group_name, cfg.team_name)
