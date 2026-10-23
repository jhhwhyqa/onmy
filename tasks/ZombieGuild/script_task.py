# This Python file uses the following encoding: utf-8
# @brief    Ryou Dokan Toppa (阴阳竂道馆突破功能)
# @author   AzurTian
# @note     draft version without full test
import re
import time
from copy import copy
from datetime import datetime
from pathlib import Path
from time import sleep
from uuid import uuid4

from module.atom.animate import RuleAnimate
from module.base.timer import Timer
from module.logger import logger
from tasks.Component.DokanCore.task_base import (
    DokanFinishedError,
    DokanNotStartedError,
    DokanRefreshLimitError,
    DokanTaskBase,
    position_offset,
)
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import BattleAction, BattleContext
from tasks.ZombieGuild.assets import ZombieGuildAssets
from tasks.ZombieGuild.config import ZombieGuild
from tasks.ZombieGuild.reward_recognition import count_blue_tickets_in_png
from tasks.ZombieGuild.task_notify import resolve_task_notifier
import tasks.ZombieGuild.page as pages


DOKAN_REWARD_SCREENSHOT_DIR = Path('log/screenshots/dokan')
DOKAN_REWARD_CAPTURE_DELAY = 1.0
DOKAN_NEXT_SELECTION_TIMEOUT = 120.0
DOKAN_NEXT_SELECTION_POLL_INTERVAL = 2.0
DOKAN_LIST_STABLE_INTERVAL = 0.3
DOKAN_LIST_STABLE_TIMEOUT = 1.5
MAX_WELFARE_DOKAN_REFRESH_COUNT = 20


class ScriptTask(DokanTaskBase, ZombieGuildAssets):
    _reuse_image_match_results: bool = True  # 仅道馆启用同帧识别结果和相同规则副本的复用。
    attack_priority_selected: bool = False
    switch_member_soul_done: bool = False
    dokan_owner_battle: bool = False  # 馆主战标识
    found_dokan_cnt: int = 0  # 已经寻找道馆的次数
    second_dokan_ready: bool = False
    # 连续"N 轮在道馆页没有任何可操作标记"就回地图页自愈（见 run_on_dokan 的兜底）
    dokan_no_marker_limit: int = 10

    CONFIG_KEY = 'zombie_guild'
    TASK_NAME = 'ZombieGuild'
    NEXT_RUN_SERVER = True
    pages = pages
    conf: ZombieGuild = None

    def _on_before_run(self) -> None:
        self.second_dokan_ready = False
        self._dokan_reward_captured_context = None
        self._dokan_reward_captured_round = None
        self._dokan_reward_captured_outside_battle = False
        self._dokan_reward_run_directory = None

    def _get_battle_screenshot_interval(self, page: pages.Page) -> float | str | None:
        # 馆员战会直接回到准备页，缩短两帧确认等待以便尽快开始下一场。
        if page == pages.page_battle:
            return 0.3
        return super()._get_battle_screenshot_interval(page)

    def _handle_prepare(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        if self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_FIRST) or self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND):
            self.dokan_owner_battle = True
        if self.dokan_owner_battle:
            return BattleAction.QUICK_EXIT
        return super()._handle_prepare(context, config)

    def _handle_in_battle(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        if self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_FIRST) or self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND):
            self.dokan_owner_battle = True  # 防止直接在战斗界面识别, 因此在这继续更新一次馆主战标识
        if self.dokan_owner_battle:
            logger.info("Skip owner battle: leave the battle before attacking")
            return BattleAction.QUICK_EXIT
        return super()._handle_in_battle(context, config)

    def _handle_reward(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        """Save the visible dojo reward before the battle handler closes it."""
        if self._capture_dokan_reward_if_visible(context) is False:
            return BattleAction.CONTINUE
        return super()._handle_reward(context, config)

    # ---------------------------------- 结算截图 / 推送 ----------------------------------
    def _capture_dokan_reward_if_visible(self, context: BattleContext | None = None) -> bool | None:
        reward_visible = self.appear(self.I_RYOU_DOKAN_BATTLE_OVER) or self.appear(self.I_UI_REWARD)
        if not reward_visible:
            if context is None:
                self._dokan_reward_captured_outside_battle = False
                self._dokan_reward_captured_context = None
                self._dokan_reward_captured_round = None
            return
        details_visible = (
            self.appear(self.I_REWARD_PARTICULARS)
            or self.appear(self.I_REWARD_PARTICULARS_ORCHI)
        )
        if details_visible:
            return
        if context is None:
            if getattr(self, '_dokan_reward_captured_outside_battle', False):
                return
        elif (getattr(self, '_dokan_reward_captured_context', None) is context
              and getattr(self, '_dokan_reward_captured_round', None) == context.continuous_count):
            return
        if not self._wait_for_dokan_reward_ready():
            return False
        if context is not None:
            self._dokan_reward_captured_context = context
            self._dokan_reward_captured_round = context.continuous_count
        self._dokan_reward_captured_outside_battle = True
        self._save_reward_image(context)
        return True

    def capture_reward_if_visible(self) -> None:
        self._capture_dokan_reward_if_visible()

    def _wait_for_dokan_reward_ready(self) -> bool:
        """结算出现后等待一秒，重新截图并确认仍在奖励页面。"""
        logger.info("Waiting 1s before taking the dojo reward screenshot")
        sleep(DOKAN_REWARD_CAPTURE_DELAY)
        self.screenshot()
        reward_visible = self.appear(self.I_RYOU_DOKAN_BATTLE_OVER) or self.appear(self.I_UI_REWARD)
        return (reward_visible and not self.appear(self.I_REWARD_PARTICULARS)
                and not self.appear(self.I_REWARD_PARTICULARS_ORCHI))

    def _reward_screenshot_directory(self) -> Path:
        run_dir = getattr(self, '_dokan_reward_run_directory', None)
        if run_dir is not None:
            return run_dir
        profile = re.sub(r'[^\w-]', '_', str(self.config.config_name)).strip('_') or 'default'
        run_id = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid4().hex[:8]}"
        self._dokan_reward_run_directory = DOKAN_REWARD_SCREENSHOT_DIR / profile / run_id
        return self._dokan_reward_run_directory

    def _save_reward_image(self, context: BattleContext | None) -> None:
        try:
            screenshot_dir = self._reward_screenshot_directory()
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            battle_key = context.battle_key if context is not None else 'dokan_settlement'
            filename = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{battle_key}.png"
            screenshot_file = screenshot_dir / filename
            self.device.image_save(screenshot_file)
            logger.info(f'Dokan reward screenshot saved: {screenshot_file}')
        except Exception as exc:
            logger.warning(f'Dokan reward screenshot failed: {exc}')

    def _push_current_run_reward_images(self) -> None:
        """Send this task run's screenshots together, then remove only sent files."""
        run_dir = getattr(self, '_dokan_reward_run_directory', None)
        if run_dir is None or not run_dir.exists():
            return
        screenshots = sorted(run_dir.glob('*.png'))
        if not screenshots:
            return
        try:
            images = [screenshot.read_bytes() for screenshot in screenshots]
            reward_summary = self._dokan_reward_blue_ticket_summary(images)
        except Exception as exc:
            logger.warning(f'Dokan reward screenshots could not be read: {exc}')
            return
        if not self.conf.dokan_config.push_reward_images:
            logger.info('Dokan reward screenshots kept because dojo notifications are disabled')
            return
        notifier = resolve_task_notifier(self.config, getattr(self.conf, 'notification_config', None))
        if not notifier.enable:
            logger.info('Dokan reward screenshots kept because notifications are disabled')
            return
        try:
            sent = notifier.push_images(images, title=f'{datetime.now():%Y-%m-%d} 道馆结算奖励',
                                        content=reward_summary,
                                        filenames=[screenshot.name for screenshot in screenshots])
        except Exception as exc:
            logger.warning(f'Dokan reward notification failed: {exc}')
            return
        if not sent:
            logger.warning(f'Dokan reward screenshots kept after failed notification: {run_dir}')
            return
        for screenshot in screenshots:
            try:
                screenshot.unlink()
            except OSError as exc:
                logger.warning(f'Cannot remove sent Dokan screenshot {screenshot}: {exc}')
        try:
            run_dir.rmdir()
        except OSError:
            pass

    def _dokan_reward_blue_ticket_summary(self, images: list[bytes]) -> str:
        """在任务结束后识别已保存的截图；识别失败仍推送原图。"""
        quantities = []
        details = []
        for index, image in enumerate(images, start=1):
            try:
                quantity = count_blue_tickets_in_png(image)
            except Exception as exc:
                logger.warning(f'Dokan blue ticket recognition failed for screenshot {index}: {exc}')
                quantity = None
            quantities.append(quantity)
            text = f'{quantity} 张' if quantity is not None else '数量未识别'
            details.append(f'截图 {index}：蓝票{text}')
            logger.info(f'Dokan reward screenshot {index}: blue tickets={quantity}')
        total = sum(quantity for quantity in quantities if quantity is not None)
        unknown_count = quantities.count(None)
        logger.info(f'Dokan reward blue tickets: total={total}, unrecognized screenshots={unknown_count}')
        if unknown_count:
            headline = f'蓝票已识别合计：{total} 张（另有 {unknown_count} 张截图数量未识别）'
        else:
            headline = f'蓝票合计：{total} 张'
        return '\n'.join([headline, *details])

    def _push_dokan_refresh_limit_notification(self) -> None:
        notifier = resolve_task_notifier(self.config, getattr(self.conf, 'notification_config', None))
        if not notifier.enable:
            logger.warning('Dokan refresh limit reached, but notifications are disabled')
            return
        try:
            notifier.push(
                title='道馆达到最大刷新次数',
                content=f'福利寮道馆已刷新{MAX_WELFARE_DOKAN_REFRESH_COUNT}次，仍未找到符合条件的道馆。任务已结束，今日不再重试。',
            )
        except Exception as exc:
            logger.warning(f'Dokan refresh limit notification failed: {exc}')

    def after_run(self, refresh_limit_reached: bool) -> None:
        self._push_current_run_reward_images()
        if refresh_limit_reached:
            self._push_dokan_refresh_limit_notification()

    # ---------------------------------- 选馆 / 策略 ----------------------------------
    def select_dokan_target(self) -> None:
        # 诊断：确认"运行这一刻"到底哪张识别图命中
        logger.info(
            f'[dokan-debug] map: finding={self.appear(self.I_RYOU_DOKAN_FINDING_DOKAN)}, '
            f'found={self.appear(self.I_RYOU_DOKAN_FOUND_DOKAN)}'
        )
        retrying_skipped_owner = self.second_dokan_ready
        if self.found_dokan_cnt > 0 and not retrying_skipped_owner:
            raise DokanNotStartedError
        if retrying_skipped_owner and self.found_dokan_cnt >= 2:
            raise DokanFinishedError
        remaining = self.update_remain_attack_count()
        if remaining < 0:
            logger.warning('未识别到道馆剩余次数，结束本次筛选')
            raise DokanNotStartedError
        if remaining == 0:
            logger.info('游戏显示道馆剩余0次，结束任务')
            raise DokanFinishedError
        if not retrying_skipped_owner and not self.ensure_dokan_created():
            logger.warning('Create Dokan failed, stop before selecting a target')
            raise DokanNotStartedError
        self.second_dokan_ready = False
        # 寻找合适道馆,找不到直接退出
        if not self.find_dokan():
            raise DokanNotStartedError
        # 寻找到道馆后等一会页面刷新
        self.wait_until_appear(self.I_RYOU_DOKAN_CENTER_TOP, True, 5)

    def run_owner_battle_from_battle_page(self) -> None:
        self.run_general_battle(self.build_quick_exit_config(self.conf.dokan_member_battle_conf),
                                battle_key='dokan_member')

    def handle_owner_state(self) -> bool:
        self.skip_owner_and_battle_again()
        return True

    def handle_vote_or_finish(self) -> None:
        self.skip_owner_and_battle_again()

    def prepare_member_soul(self) -> None:
        self.switch_soul_in_dokan()

    def should_retry_today(self) -> bool:
        return self.conf.attack_count_config.remain_attack_count == 1

    # ---------------------------------- 福利寮筛选 ----------------------------------
    def _wait_for_dokan_list_ready(self) -> bool:
        """列表连续两次稳定后使用当前帧筛选，避免滑动中读取旧位置。"""
        animation = RuleAnimate(self.I_RIGHTPAD_POINT_BOUNTY, threshold=0.98, name='DOKAN_LIST')
        deadline = time.monotonic() + DOKAN_LIST_STABLE_TIMEOUT
        stable_checks = 0
        while time.monotonic() < deadline:
            check_started = time.monotonic()
            self.screenshot()
            if time.monotonic() >= deadline:
                break
            stable_checks = stable_checks + 1 if animation.stable(
                self.device.image, frame_id=self.device.image_frame_id) else 0
            checked_at = time.monotonic()
            if checked_at >= deadline:
                break
            if stable_checks >= 2:
                return True
            delay = min(max(0.0, DOKAN_LIST_STABLE_INTERVAL - (checked_at - check_started)),
                        deadline - checked_at)
            if delay > 0:
                sleep(delay)
        logger.warning('道馆列表仍在变化，跳过当前屏，继续筛选')
        return False

    def find_dokan(self) -> bool:
        """只挑战带“鑫”图标且符合防守人数要求的福利寮。"""
        self.found_dokan_cnt += 1
        configured_refresh_count = self.config.zombie_guild.dokan_config.find_dokan_refresh_count
        num_fresh = 0
        # 赏金图标仅用于定位列表项，不读取赏金或计算系数。
        backup = {'i_point_bounty': self.I_RIGHTPAD_POINT_BOUNTY.roi_back,
                  'i_point_people_num': self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back,
                  'i_xin_icon': self.I_RIGHTPAD_XIN_ICON.roi_back}

        def restore_roi():
            self.I_RIGHTPAD_POINT_BOUNTY.roi_back = backup['i_point_bounty']
            self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back = backup['i_point_people_num']
            self.I_RIGHTPAD_XIN_ICON.roi_back = backup['i_xin_icon']

        def find_challengeable():
            restore_roi()
            self.device.click_record_clear()
            if not self._wait_for_dokan_list_ready():
                return False
            candidates = self.find_all_element(self.I_RIGHTPAD_POINT_BOUNTY, (0, 0, 0, 50))
            logger.info(f'find elements list:{candidates}')
            xin_rules = []
            for idx, item in enumerate(candidates):
                rule = copy(self.I_RIGHTPAD_XIN_ICON)
                rule.roi_front = list(rule.roi_front)
                rule.roi_back = (item[0] - 15, max(0, item[1] - 90), 100, 95)
                xin_rules.append(rule)
            # 同一帧批量判断当前屏的图标，普通道馆无需逐项截图或打开详情。
            self.prepare_appear_cache(xin_rules)
            welfare_candidates = []
            for idx, (item, rule) in enumerate(zip(candidates, xin_rules)):
                if self.appear(rule):
                    welfare_candidates.append((idx, item, rule))
                else:
                    logger.info(f"skip dojo without Xin emblem: idx={idx} item={item}")
            for idx, item, rule in welfare_candidates:
                self.device.click_record_clear()
                logger.info(f"------start no.{idx} =={item}-----------")
                self.screenshot()
                while self.appear(self.I_CENTER_CHALLENGE):
                    self.click(self.C_DOKAN_CANCEL_SELECT_DOKAN, interval=1.5)
                    self.wait_animate_stable(self.C_DOKAN_CANCEL_SELECT_DOKAN_CHECK_ANIMATE,
                                             interval=0.5, timeout=1.5)
                # 关闭详情会改变画面，点击前在最新帧复核候选，防止列表位置变化。
                if not self.appear(rule):
                    logger.info(f"Xin emblem moved before selection: idx={idx} item={item}")
                    continue
                self.I_RIGHTPAD_POINT_BOUNTY.roi_back = position_offset(item, (-10, -10, 20, 20))
                if not self.ui_click_until_appear_or_timeout(self.I_RIGHTPAD_POINT_BOUNTY, self.I_CENTER_CHALLENGE,
                                                             interval=1.5, timeout=8):
                    logger.info(f"can't find challenge button,idx={idx} item={item}")
                    continue
                self.screenshot()
                if not self.appear(self.I_CENTER_POINT_PEOPLE_NUMBER):
                    logger.warning(f"can't find point people number image, item={item}")
                    continue
                self.O_DOKAN_CENTER_PEOPLE_NUMBER.roi = position_offset(
                    self.I_CENTER_POINT_PEOPLE_NUMBER.roi_front, (0, 0, 0, 30))
                people = self.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text(self.device.image)
                match = re.search(r"(\d+)", people)
                if not match:
                    logger.warning(f"can't find people number in ocr result,item={item}, people={people}")
                    continue
                people = float(match.group())
                min_people_num = self.config.zombie_guild.dokan_config.min_people_num
                if num_fresh > configured_refresh_count:
                    min_people_num /= 2
                if people < min_people_num:
                    logger.info(f"welfare guild people num too small: {people} < {min_people_num}")
                    continue
                logger.info(f"find welfare guild: people_num:{people}")
                return True
            return False

        try:
            while num_fresh < MAX_WELFARE_DOKAN_REFRESH_COUNT:
                for _ in range(3):
                    sleep(3)
                    if find_challengeable():
                        logger.info("find challengeable welfare dokan")
                        self.ui_click(self.I_CENTER_CHALLENGE, self.I_CHALLENGE_ENSURE, interval=1)
                        self.ui_click_until_disappear(self.I_CHALLENGE_ENSURE, interval=1)
                        self.config.zombie_guild.attack_count_config.del_attack_count(1, self.config.save)
                        return True
                    self.swipe(self.S_DOKAN_LIST_UP)
                restore_roi()
                logger.info("=========refresh dokan list=========")
                self.ui_click(self.C_DOKAN_REFRESH, self.I_REFRESH_ENSURE, interval=1)
                self.ui_click_until_disappear(self.I_REFRESH_ENSURE, interval=1)
                num_fresh += 1
                logger.info("Refresh Done")
                if num_fresh == configured_refresh_count + 1:
                    logger.info('Welfare guild minimum defender count reduced by half')
            logger.warning(f'No eligible Xin-emblem dojo after {num_fresh} refreshes')
            raise DokanRefreshLimitError
        finally:
            restore_roi()

    def ensure_dokan_created(self) -> bool:
        """灰色按钮表示已建立道馆；可点击时先完成建立，再开始筛选。"""
        for attempt in range(1, 3):
            self.screenshot()
            if self.appear(self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE):
                return self.creat_dokan()

            button = next((item for item in (
                self.I_RYOU_DOKAN_CREATE_DOKAN, self.I_RYOU_DOKAN_HAVE_DOKAN
            ) if self.appear(item)), None)
            if button is None:
                logger.warning(
                    f'Dokan create/have marker not recognized: '
                    f'attempt={attempt}/2'
                )
                sleep(0.5)
                continue

            # 两个按钮的轮廓相同，模板相关性超过 0.96，必须额外区分颜色。
            # 只取图标中央，避开彩色地图背景和底部文字。
            x, y, w, h = button.roi_front
            icon = self.device.image[
                y + h // 4:y + 3 * h // 4,
                x + w // 4:x + 3 * w // 4,
                :3,
            ]
            if icon.size == 0:
                continue
            mean_chroma = float((icon.max(axis=2) - icon.min(axis=2)).mean())
            if mean_chroma < 10:
                logger.info('Dokan create button is grey; own Dokan already exists, start selecting a target')
                return True

            logger.info(f'Create Dokan before selecting a target: attempt={attempt}/2')
            self.click(button)

            if self.wait_until_appear(
                    self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE,
                    True,
                    3,
            ):
                logger.info('Create Dokan dialog opened')
                return self.creat_dokan()

        logger.warning(
            'Could not confirm that own Dokan exists or create it; '
            'stop before selecting a target'
        )
        return False

    def skip_owner_and_battle_again(self) -> bool:
        """馆主阶段放弃突破；有第二次机会时再战，否则保留赏金。"""
        can_retry = self.can_battle_again()
        remaining = None
        retry_wait_logged = False
        abandon_clicked = False
        vote_click_failures = 0
        timeout = Timer(15).start()
        while not timeout.reached():
            self.screenshot()
            # 放弃突破的投票确认弹窗是模态的，会吞掉其它按钮的点击，必须最先处理
            if self.appear(self.I_DOKAN_ABANDONED_TOPPA_ENSURE):
                logger.info('Confirm abandon Dokan vote')
                self.appear_then_click(self.I_DOKAN_ABANDONED_TOPPA_ENSURE, interval=1)
                abandon_clicked = True
                sleep(0.5)
                continue
            settlement_visible = (self.appear(self.I_RYOU_DOKAN_TODAY_ATTACK_COUNT)
                                  or self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE))
            if settlement_visible and (remaining is None or remaining < 0):
                remaining = self.update_remain_attack_count()
                can_retry = self.can_battle_again()
            # 投票控件优先于今日次数提示，第一次放弃后该提示也会出现。
            if can_retry and self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN):
                if self.appear_then_click(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN, interval=1):
                    self.wait_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN, timeout=3)
                    self.screenshot()
                    if not self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN):
                        logger.info("Skipped owner battle and selected Battle Again")
                        self.wait_for_next_dokan_selection()
                        return True
                    vote_click_failures += 1
                    if vote_click_failures >= 3:
                        logger.warning(
                            'Battle Again did not respond; stop clicking to avoid the click limit'
                        )
                        return False
            elif not can_retry and self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY):
                if self.appear_then_click(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY, interval=1):
                    self.wait_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY, timeout=3)
                    self.screenshot()
                    if not self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY):
                        self.dokan_owner_battle = False
                        logger.info("Skipped owner battle and kept the bounty on the last attempt")
                        return True
                    vote_click_failures += 1
                    if vote_click_failures >= 3:
                        logger.warning(
                            'Keep Bounty did not respond; stop clicking to avoid the click limit'
                        )
                        return False
            elif self.appear(self.I_RYOU_DOKAN_TOPPA_RANK):
                self.click(self.C_DOKAN_TOPPA_RANK_CLOSE_AREA, interval=1)
            elif (self.appear(self.I_DOKAN_ABANDONED_TOPPA_TITLE)
                  and self.appear(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED)):
                self.appear_then_click(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED, interval=1)
            elif settlement_visible:
                if remaining < 0 or can_retry:
                    if not retry_wait_logged:
                        logger.info(f"Dokan has {remaining} remaining attempt(s); waiting for the Battle Again vote")
                        retry_wait_logged = True
                    # 本次已结束，等待投票出现，不能重新点击放弃突破。
                else:
                    self.dokan_owner_battle = False
                    logger.info("Dokan challenge ended while skipping owner battle")
                    raise DokanFinishedError
            elif not abandon_clicked and self.appear(self.I_DOKAN_ABANDONED_TOPPA_RIGHT):
                if self.appear_then_click(self.I_DOKAN_ABANDONED_TOPPA_RIGHT, interval=1):
                    abandon_clicked = True
            elif not abandon_clicked and self.appear(self.I_DOKAN_ABANDONED_TOPPA):
                if self.appear_then_click(self.I_DOKAN_ABANDONED_TOPPA, interval=1):
                    abandon_clicked = True
            sleep(0.5)
        logger.warning("Skip owner battle timed out before voting")
        return False

    def can_battle_again(self) -> bool:
        """以游戏识别的剩余次数决定再战，单次任务最多挑战两馆。"""
        attack_count = self.conf.attack_count_config
        return attack_count.remain_attack_count > 0 and self.found_dokan_cnt < 2

    def wait_for_next_dokan_selection(self) -> None:
        """Wait for Battle Again to return to the map before the second selection."""
        logger.info(f"道馆再战：立即开始识别筛选界面，检测间隔 {DOKAN_NEXT_SELECTION_POLL_INTERVAL:g} 秒，"
                    f"最长等待 {DOKAN_NEXT_SELECTION_TIMEOUT:g} 秒")
        # PAUSE 只延长卡死检测，实际等待始终截图识别，不能整段休眠。
        self.device.stuck_record_clear()
        self.device.stuck_record_add('PAUSE')
        started_at = time.monotonic()
        deadline = started_at + DOKAN_NEXT_SELECTION_TIMEOUT
        next_log_at = started_at + 10
        checks = 0
        screenshot_seconds = recognition_seconds = 0.0
        selection_visible = False
        try:
            while time.monotonic() < deadline:
                check_started_at = time.monotonic()
                self.screenshot()
                screenshot_finished_at = time.monotonic()
                screenshot_seconds = screenshot_finished_at - check_started_at
                recognition_seconds = 0.0
                if screenshot_finished_at >= deadline:
                    break
                selection_visible = self.appear(self.I_RYOU_DOKAN_FINDING_DOKAN)
                checked_at = time.monotonic()
                recognition_seconds = checked_at - screenshot_finished_at
                checks += 1
                # 截图或识别调用可能阻塞，返回后仍须核对完整的等待耗时。
                if checked_at >= deadline:
                    selection_visible = False
                    break
                if selection_visible:
                    logger.info(f"已识别道馆筛选界面：等待 {checked_at - started_at:.1f} 秒，"
                                f"检测 {checks} 次，继续第二次道馆")
                    break
                if checked_at >= next_log_at:
                    logger.info(f"道馆再战等待：已等待 {checked_at - started_at:.1f}/120 秒，"
                                f"检测 {checks} 次；最近截图 {screenshot_seconds:.2f} 秒，"
                                f"识图 {recognition_seconds:.2f} 秒")
                    next_log_at = checked_at + 10
                delay = min(max(0.0, DOKAN_NEXT_SELECTION_POLL_INTERVAL
                                - (checked_at - check_started_at)), deadline - checked_at)
                if delay > 0:
                    sleep(delay)
            if not selection_visible:
                logger.warning(f"道馆再战等待超时：已等待 {time.monotonic() - started_at:.1f}/120 秒，"
                               f"检测 {checks} 次；最近截图 {screenshot_seconds:.2f} 秒，"
                               f"识图 {recognition_seconds:.2f} 秒")
                raise DokanNotStartedError("Battle Again did not return to dojo selection")
        finally:
            self.device.stuck_record_clear()
        self.dokan_owner_battle = False
        self.attack_priority_selected = False
        self.second_dokan_ready = True

    def switch_soul_in_dokan(self) -> None:
        """本次任务仅切换一次馆员御魂，第二次道馆沿用。"""
        if self.switch_member_soul_done:
            return
        logger.hr('Start switch soul', 2)
        switch_soul = self.config.zombie_guild.dokan_member_switch_soul
        if switch_soul.enable:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul(switch_soul.switch_group_team)
            self.goto_page(pages.page_dokan)
        elif switch_soul.enable_switch_by_name:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul_by_name(switch_soul.group_name, switch_soul.team_name)
            self.goto_page(pages.page_dokan)
        else:
            logger.info('Skip switch soul')
        self.switch_member_soul_done = True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
