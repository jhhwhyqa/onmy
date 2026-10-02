import time

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_battle, page_battle_prepare
from tasks.IbukiArena.assets import IbukiArenaAssets
from tasks.IbukiArena.config import IbukiArena
import tasks.IbukiArena.page as pages


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, IbukiArenaAssets):
    """狭间幻境（伊吹之擂）单人战斗"""

    conf: IbukiArena = None

    # 连续识别不到挑战次数时的退出保护(避免识别失败后无脑点挑战)
    ocr_fail_limit = 3
    # 连续把"已在战斗页"交回通用战斗的上限(避免在两个战斗页之间来回打转)
    battle_handoff_limit = 3

    def run(self):
        self.conf = self.config.ibuki_arena
        self.switch_soul()
        self.goto_page(pages.page_ibuki)
        success = self.run_arena()
        self.goto_page(pages.page_main)
        self.set_next_run(task='IbukiArena', success=success, finish=success)
        raise TaskEnd

    def run_arena(self) -> bool:
        """进入狭间幻境并循环挑战, 次数上限以右上角实时识别为准

        右上角是"剩余可挑战次数/上限"(例如 3/6 表示还能挑战 3 次),
        剩余为 0 即当天打完。

        Returns:
            bool: True 表示次数正常跑完; False 表示挑战次数识别失败提前退出
        """
        logger.hr('IbukiArena battle', 2)
        ocr_fail_count = 0
        battle_handoff_count = 0
        last_page = None
        # 兜底：只有"页面变了"或"真的点了东西"才算有进展；连续 30s 毫无进展就自己退出，
        # 不要空转到 60s 的卡死检测把整个任务崩掉。
        progress_timer = Timer(30).start()
        while True:
            self.screenshot()
            # 剧情/动画: 跳过
            if self.appear_then_click(self.I_SKIP, interval=0.8):
                logger.info('Skip story')
                progress_timer.reset()
                continue

            current_page = self.get_current_page()
            if current_page != last_page:
                progress_timer.reset()
                last_page = current_page

            if current_page == pages.page_ibuki:
                battle_handoff_count = 0
                # 进入狭间幻境
                if self.appear_then_click(self.I_GOTO_ARENA, interval=1.2):
                    logger.info('Enter IbukiArena by stage entry')
                    continue
            elif current_page == pages.page_ibuki_arena:
                battle_handoff_count = 0
                # 右上角实时显示 剩余可挑战次数/上限
                remain, used, total = self.O_CHALLENGE_TIMES.ocr(self.device.image)
                if total <= 0:
                    ocr_fail_count += 1
                    logger.warning(
                        f'Cannot read challenge times [{ocr_fail_count}/{self.ocr_fail_limit}]'
                    )
                    if ocr_fail_count >= self.ocr_fail_limit:
                        logger.warning('Challenge times unrecognizable, exit')
                        return False
                    time.sleep(0.5)
                    continue
                ocr_fail_count = 0
                logger.info(f'Challenge times remain {remain}/{total}, used {used}')
                if remain <= 0:
                    logger.info('No challenge times left, exit')
                    return True
                self.switch_lock()
                # 挑战
                if self.appear_then_click(self.I_CHALLENGE, interval=1.2):
                    logger.info(f'remain {remain}/{total}')
                    # 不能把 page_ibuki_arena 当 exit_matcher：该页的识别图之一就是
                    # I_CHALLENGE 本身，而点它正是进战斗的动作；run_general_battle 一开
                    # 始检测不到战斗页时就会评估 exit_matcher，此时人还站在擂台页 →
                    # 立刻命中 → 这一场直接判 Lose 退出、根本没打。改为不传，走默认的
                    # "结算后页面持续识别不到 2.5s 即结束"，打完回到擂台页同样能正常收尾。
                    self.run_general_battle(config=self.conf.general_battle_config)
                    # 打完一场本身就算进展：战斗可能耗时 60s+，且结束后页面可能和
                    # 进战斗前同为擂台页，"页面变化"判据不会重置，这里显式重置。
                    progress_timer.reset()
                    self.device.stuck_record_clear()
                    continue
            elif current_page in (page_battle_prepare, page_battle):
                # 兜底：停在战斗页(准备/战斗中)说明有一场待打的战斗——例如上一次
                # run_general_battle 提前返回了。这里交回通用战斗把它打完（点准备 →
                # 打完 → 结算），而不是在本循环里干等到卡死检测。
                if battle_handoff_count >= self.battle_handoff_limit:
                    logger.warning(
                        f'IbukiArena: still in battle page after '
                        f'{battle_handoff_count} handoffs, exit'
                    )
                    return False
                battle_handoff_count += 1
                logger.info(
                    f'IbukiArena: in battle page, hand over to general battle '
                    f'[{battle_handoff_count}/{self.battle_handoff_limit}]'
                )
                self.run_general_battle(config=self.conf.general_battle_config)
                # 同上：一次战斗跑完算进展（这一支靠 battle_handoff_count 封顶兜住打转）
                progress_timer.reset()
                self.device.stuck_record_clear()
                continue

            if progress_timer.reached():
                logger.warning(
                    f'IbukiArena page not progressing (current: {current_page}), exit'
                )
                return False
            time.sleep(0.2)

    def switch_lock(self):
        if self.conf.general_battle_config.lock_team_enable:
            self.ui_click(self.I_ACT_UNLOCK, self.I_ACT_LOCK)
            return
        self.ui_click(self.I_ACT_LOCK, self.I_ACT_UNLOCK)

    def switch_soul(self):
        """切换御魂"""
        if self.conf.switch_soul_config.enable:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul(self.conf.switch_soul_config.switch_group_team)
        if self.conf.switch_soul_config.enable_switch_by_name:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul_by_name(
                self.conf.switch_soul_config.group_name,
                self.conf.switch_soul_config.team_name,
            )


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
