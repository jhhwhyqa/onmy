# This Python file uses the following encoding: utf-8
import re
from time import sleep

from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralInvite.general_invite import GeneralInvite
from tasks.Component.GeneralRoom.general_room import GeneralRoom
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.LBS.assets import LBSAssets
from tasks.LBS.config import LBS, LBSMode
import tasks.LBS.page as pages


class ScriptTask(
    GeneralBattle, GeneralInvite, GeneralRoom, GameUi, SwitchSoul, LBSAssets
):
    """线下庆典（现世妖约）组队挑战。"""

    conf: LBS

    def run(self) -> None:
        self.conf = self.config.lbs
        self._switch_soul()
        if self.conf.lbs_config.buy_blessing_enable:
            self._buy_blessing()

        if self.conf.lbs_config.run_mode == LBSMode.SOLO:
            success = self.run_solo_team()
        else:
            success = self.run_public_team()

        self.goto_page(pages.page_main)
        self.set_next_run('LBS', finish=success, success=success)
        raise TaskEnd

    def _switch_soul(self) -> None:
        if self.conf.switch_soul.enable:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul(self.conf.switch_soul.switch_group_team)
        if self.conf.switch_soul.enable_switch_by_name:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul_by_name(
                self.conf.switch_soul.group_name,
                self.conf.switch_soul.team_name,
            )

    def _buy_blessing(self) -> None:
        """购买当日限购一次、价值 100 勾玉的现世祝福。"""
        self.goto_page(pages.page_lbs_shop)
        self.screenshot()
        if not self.appear(self.I_LBS_BLESSING):
            logger.info(f'LBS blessing already purchased today')
            return
        logger.info(f'Buy LBS blessing for 100 jade')
        self.ui_click(self.I_LBS_BLESSING, self.I_BUY_BLESSING, interval=1)
        self.ui_get_reward(self.I_BUY_BLESSING)
        logger.info(f'LBS blessing purchase complete')

    def run_public_team(self) -> bool:
        """公开房间：随机匹配路人，凑齐队友后开战。"""
        return self._run_team(solo=False)

    def run_solo_team(self) -> bool:
        """不公开(仅邀请)房间：不等队友，进房后直接挑战单刷。"""
        return self._run_team(solo=True)

    def _run_team(self, solo: bool) -> bool:
        """活动页面显示的挑战次数耗尽后结束。"""
        logger.hr(f'Start LBS {"solo" if solo else "public"} team', 3)
        while True:
            # 每场结算都会回到活动页（或短暂经过地图页），下一轮必须重新建房。
            self.goto_page(pages.page_lbs)
            remain_count = self._remaining_challenge_count()
            if remain_count is None:
                logger.error('Cannot read LBS remaining challenge count')
                return False
            if remain_count <= 0:
                logger.info('LBS challenge count exhausted')
                return True
            if not self.create_room(self.I_LBS_TEAM):
                return False
            if solo:
                # 不公开(仅邀请)，房间只有自己一个人也可以开战
                self.ensure_private(self.I_GI_IN_ROOM)
            else:
                self.ensure_public()
            if not self.create_ensure():
                return False
            if solo:
                if not self._wait_solo_room():
                    return False
            elif not self._wait_random_teammate():
                return False

            self.run_general_battle(
                config=self.conf.general_battle_config,
                exit_matcher=self._team_exit_matcher,
            )
        return True

    def _wait_random_teammate(self) -> bool:
        """公开房间：等待一名路人加入并点击挑战。"""
        while True:
            self.screenshot()
            if not self.is_in_room(False):
                if self._is_room_dead():
                    logger.warning('LBS random-match room was destroyed')
                    return False
                continue
            # 通用双人房中 I_ADD_1 表示空余队友位；消失即已有路人加入。
            if self.appear(self.I_ADD_1):
                continue
            logger.info(f'A random teammate joined LBS room, start challenge')
            self.click_fire()
            return True

    def _wait_solo_room(self) -> bool:
        """不公开房间：进入房间后不等队友，直接点击挑战单刷。"""
        while True:
            self.screenshot()
            if not self.is_in_room(False):
                if self._is_room_dead():
                    logger.warning('LBS solo room was destroyed')
                    return False
                continue
            logger.info(f'LBS solo room is ready, start challenge without teammate')
            self.click_fire()
            return True

    def _remaining_challenge_count(self) -> int | None:
        """读取活动页右下角的“挑战次数：剩余/总数”。"""
        count, _, _ = self.O_LBS_CHALLENGE_COUNT.ocr(self.device.image) or ''
        if not count:
            logger.warning(f'Unexpected LBS challenge-count OCR: {count!r}')
            return None
        return count

    def _is_room_dead(self) -> bool:
        sleep(0.5)
        if self.appear(self.I_MATCHING) or self.appear(self.I_CHECK_EXPLORATION):
            sleep(0.5)
            return self.appear(self.I_MATCHING) or self.appear(self.I_CHECK_EXPLORATION)
        return False

    def _team_exit_matcher(self) -> bool:
        # 结算动画会短暂经过现世地图；该页已注册并可导航回活动首页，
        # 因此同样视为已离开战斗，避免被后续导航当成未知页面。
        return self.appear(self.I_LBS_TEAM) or self.appear(self.I_CHECK_LBS_MAP)
