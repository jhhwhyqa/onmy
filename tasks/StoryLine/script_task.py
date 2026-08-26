# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
#
# 主线剧情(StoryLine)
import time
from pathlib import Path

from module.base.timer import Timer
from module.exception import TaskEnd, ScriptError
from module.atom.ocr import RuleOcr
from module.logger import logger

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.assets import GameUiAssets
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Exploration.assets import ExplorationAssets
from tasks.StoryLine.assets import StoryLineAssets


class ScriptTask(GameUi, GeneralBattle, StoryLineAssets):
    # 连续多少秒无任何可识别元素才视为"可能卡住"→ 随机点击一次推进（收窄触发，正常停顿不触发）
    RANDOM_CLICK_IDLE = 3
    # 单段内最多随机点击次数，避免反复无效点击
    MAX_RANDOM_CLICKS = 2
    # 多少秒无有效推进（没有任何可识别动作）→ 任务失败
    STUCK_TIMEOUT = 60
    # 「⋯」/「？」徽章连续几帧位置一致才认为"已静止"再进行点击（避免过场/运镜移动时误点）
    STABLE_FRAMES = 3
    # 位置容差(px)：两次匹配中心差 <= 该值视为同一位置（静止）
    STABLE_TOL = 8
    # 「跳过」识别窗口：待命后多少秒内未识别到即放弃识别（并非每次都会出现跳过）
    SKIP_DETECT_WINDOW = 3
    # 剧情结束回到庭院后自动弹窗取消按钮的等待秒数
    POPUP_DISMISS_TIMEOUT = 3

    def _is_after_battle_story(self) -> bool:
        """战斗结算后是否已回到剧情画面或庭院主界面。

        作为通用战斗的 exit_matcher：剧情战斗结束、奖励消失后，
        只要再次出现剧情对话元素(眼睛/三点/问号)或回庭院标志，
        就立刻交还控制权，而非等待 `_handle_missing_battle_page` 的固定兜底耗时。
        该 matcher 仅在本段曾进入战斗结算/奖励页时才被求值，不会在战斗中途误触发。
        """
        return (self.appear(self.I_STORY_DIALOG_EYE)
                or self.appear(self.I_STORY_DIALOG_DOTS)
                or self.appear(self.I_STORY_DIALOG_QUESTION)
                or self.appear(GameUiAssets.I_CHECK_MAIN))

    def run(self):
        con = self.config.story_line.story_config
        limit_seconds = (con.limit_time.hour * 3600
                         + con.limit_time.minute * 60
                         + con.limit_time.second)
        deadline = time.time() + limit_seconds

        logger.hr('StoryLine start', level=2)
        for run_idx in range(con.run_count):
            if time.time() >= deadline:
                logger.warning('StoryLine: limit_time reached, stop before next run')
                break
            logger.info(f'Story run {run_idx + 1}/{con.run_count}')
            self._play_one_story(con, deadline)
            # 剧情结束回到庭院后可能有自动弹窗 → 取消
            self._dismiss_courtyard_popup()
            # 一段剧情结束(「终」)后：等级限制检查，被卡住则整体结束任务
            if self._level_limited():
                logger.info('StoryLine: level limited, stop task')
                break

        logger.info(f'StoryLine finished {con.run_count} run(s)')
        self.set_next_run(task='StoryLine', success=True, finish=False)
        raise TaskEnd('StoryLine')

    def _play_one_story(self, con, deadline):
        """
        完成一段剧情：从庭院进入 → 播放(对话/跳过/战斗)；检测到「终」标记(模板)即视为本段完成并返回。
        连续 RANDOM_CLICK_IDLE 秒无任何可识别元素 → 随机点击一次推进(限 MAX_RANDOM_CLICKS 次)；
        STUCK_TIMEOUT 秒无有效推进 → 任务失败。
        """
        stuck_timer = Timer(self.STUCK_TIMEOUT).start()
        idle_timer = Timer(self.RANDOM_CLICK_IDLE).start()
        self.random_click_left = self.MAX_RANDOM_CLICKS
        round_count = 0
        self._story_started = False
        # 两个「跳过」的识别是状态门控：只在对应触发动作后生效，点过一次即消耗，等待下次触发
        self._can_confirm_skip = False
        self._can_bottom_skip = False
        self._bottom_skip_deadline = 0

        while round_count < con.max_rounds and time.time() < deadline:
            self.screenshot()
            # 结束判定：「终」模板命中视为本段剧情完成（跑完一次）；任务整体结束由 run() 的等级限制/次数/时间处理
            if self._story_started and self.appear(self.I_STORY_END):
                logger.info('Story run finished (终)')
                return
            if self._dob() > 0:
                # 任意剧情动作(三点/跳过/确认/战斗)都视为已进入剧情，
                # 以便用户中途退出后重新进入时也能各自触发并正常判定结束
                self._story_started = True
                round_count += 1
                stuck_timer.reset()
                idle_timer.reset()
                continue
            # 收窄：仅当连续 12s 无任何可识别元素(可能卡住)且还有配额 → 随机点击一次
            # 只对「已进入剧情」的卡顿做随机点击；两段剧情之间/庭院内尚未进入剧情时不随机点击
            if self._story_started and idle_timer.reached() and self.random_click_left > 0:
                logger.info(f'StoryLine: no recognition for {self.RANDOM_CLICK_IDLE}s, random click (left {self.random_click_left})')
                self.click(self.C_STORY_DIALOG_TAP)
                self.random_click_left -= 1
                idle_timer.reset()
                # 随机点击后识别一次底部跳过（与其它触发同一 3s 窗口）
                self._arm_bottom_skip()
                continue
            # 60s 无有效推进 → 任务失败
            if stuck_timer.reached():
                raise ScriptError('StoryLine stuck: no progress for 60s')
            time.sleep(0.3)

    def _level_limited(self) -> bool:
        """一段剧情结束(「终」)后调用：是否因等级要求而结束整个任务。

        等级计数(Lv.xx)渲染在与入口「三点」相同的位置：识别到 Lv.xx 时三点被覆盖、
        不再命中，无法再点击三点推进剧情。因此检测到 Lv.xx 即返回 True(任务整体结束)；
        未检测到 → 三点可见、可继续推进 → 返回 False(等待下一次「终」)。

        未配置 O_STORY_LEVEL 资产时恒返回 False。
        """
        if not hasattr(self, 'O_STORY_LEVEL'):
            return False
        try:
            boxes = self.O_STORY_LEVEL.detect_and_ocr(self.device.image, logDisplay=False)
        except Exception:
            return False
        return any('lv' in str(getattr(b, 'ocr_text', '')).lower() for b in boxes)

    def _ocr_contains_click(self, target: RuleOcr, keyword: str) -> bool:
        """
        OCR 文本包含 keyword 即点击匹配框中心（容错过读）。

        剧情底部「跳过」按钮实际可能被识别为"跳跳过"等含多余字符的文本，
        按 `Single` 模式严格等值会漏掉，这里放宽为"包含即命中"。
        """
        if not isinstance(target, RuleOcr):
            return False
        result = target.ocr(self.device.image)
        if keyword not in result:
            return False
        x, y, w, h = target.roi
        self.device.click(x + w // 2, y + h // 2, control_name=target.name)
        return True

    def _stable_center_click(self, target) -> bool:
        """
        目标在当前帧匹配框中心已连续稳定 STABLE_FRAMES 帧后才点击。

        剧情推进中「⋯」/「？」会随过场动画、运镜移动，位置不稳时不一定点得到真实徽章，
        还可能误点装饰元素；等位置不再移动、跨帧一致后再点中心，可避免这类误点。
        徽章移开/消失时复位计数。返回是否已点击。
        """
        if not self.appear(target):
            if hasattr(self, '_stable_pos'):
                self._stable_pos.pop(target.name, None)
            return False
        x, y, w, h = target.roi_front
        cx, cy = x + w // 2, y + h // 2
        if not hasattr(self, '_stable_pos'):
            self._stable_pos = {}
        prev = self._stable_pos.get(target.name)
        if prev is None or (abs(prev[0] - cx) > self.STABLE_TOL or abs(prev[1] - cy) > self.STABLE_TOL):
            self._stable_pos[target.name] = (cx, cy, 1)
            return False
        self._stable_pos[target.name] = (cx, cy, prev[2] + 1)
        if self._stable_pos[target.name][2] >= self.STABLE_FRAMES:
            self.device.click(cx, cy, control_name=target.name)
            return True
        return False

    def _appear_click_center(self, target, interval=None) -> bool:
        """
        出现即点击其匹配框「中心」，而非随机点。
        手裁/非本项目配置的资产匹配框可能含背景或偏大，随机点易落边角而点不到。
        返回是否命中并点击。
        """
        if isinstance(target, RuleOcr):
            if not self.ocr_appear(target, interval):
                return False
            x, y, w, h = target.roi
        else:
            if not self.appear(target, interval=interval):
                return False
            x, y, w, h = target.roi_front
        self.device.click(x + w // 2, y + h // 2, control_name=target.name)
        return True

    def _arm_bottom_skip(self) -> None:
        """「底部跳过」进入待命，并开启 SKIP_DETECT_WINDOW 秒的识别窗口。"""
        self._can_bottom_skip = True
        self._bottom_skip_deadline = time.time() + self.SKIP_DETECT_WINDOW

    def _dismiss_courtyard_popup(self) -> None:
        """剧情结束回到庭院后处理自动弹窗：出现取消按钮(模板)则点击。

        弹窗不一定出现；I_STORY_POPUP_CANCEL 由 image.json 标注，未提供图片则跳过。
        最多等待 POPUP_DISMISS_TIMEOUT 秒。
        """
        if not hasattr(self, 'I_STORY_POPUP_CANCEL'):
            return
        if not Path(self.I_STORY_POPUP_CANCEL.file).exists():
            return
        timeout = Timer(self.POPUP_DISMISS_TIMEOUT).start()
        while not timeout.reached():
            self.screenshot()
            if self._appear_click_center(self.I_STORY_POPUP_CANCEL):
                logger.info('StoryLine: courtyard popup cancelled')
                return
            time.sleep(0.5)

    def _dob(self) -> int:
        """
        尝试推进剧情。返回本轮是否执行了有效动作(1=是, 0=否)。
        剧情里反复出现「三点」与「跳过」，每次只做一个动作。
        推进优先级：战斗 > 确认跳过 > 底部「跳过」> 三点 > 问号 > 眼睛 > 右上跳过。
        (右上跳过放最后，避免在对话界面误抢「三点」的点击)
        动作互斥，避免重复点击。所有非本项目配置资产均点击中心附近。
        """
        # 每轮开头清空点击记录，避免"跳过↔三点"的正常反复被全局点击守卫误判为卡死
        self.device.click_record_clear()

        # ---- 剧情战斗：复用探索的「普通进入战斗」按钮(项目已有资产，走项目默认点击)，固定走通用战斗 ----
        if self.appear(ExplorationAssets.I_NORMAL_BATTLE_BUTTON):
            self.appear_then_click(ExplorationAssets.I_NORMAL_BATTLE_BUTTON, interval=0.8)
            # 等最多 3 秒确认真的进入战斗准备页(出现「准备」高亮)，否则视为误触/未命中，跳过战斗
            if self.wait_until_appear(self.I_PREPARE_HIGHLIGHT, wait_time=3):
                self.run_general_battle(self.config.story_line.general_battle_config, battle_key="story", exit_matcher=self._is_after_battle_story)
                # 战斗结束后重置随机点击配额，避免战斗后卡住时无随机点击可恢复
                self.random_click_left = self.MAX_RANDOM_CLICKS
            else:
                logger.warning('StoryLine: battle enter clicked but prepare page not detected, skip battle')
            # 战斗结束后识别底部跳过(2s 窗口)
            self._arm_bottom_skip()
            return 1

        # ---- 剧情可能"直接进入战斗"(庭院三点进剧情后直接到准备页，无进入按钮)：检测到准备页即走通用战斗 ----
        if self.appear(self.I_PREPARE_HIGHLIGHT):
            logger.info('StoryLine: entered battle-prep directly, start general battle')
            self.run_general_battle(self.config.story_line.general_battle_config, battle_key="story", exit_matcher=self._is_after_battle_story)
            # 战斗结束后重置随机点击配额，避免战斗后卡住时无随机点击可恢复
            self.random_click_left = self.MAX_RANDOM_CLICKS
            # 战斗结束后识别底部跳过(2s 窗口)
            self._arm_bottom_skip()
            return 1

        # ---- 确认跳过（右上跳过按钮后的二次确认，OCR）：仅当点击过右上跳过按钮后才识别，点击即消耗 ----
        if getattr(self, '_can_confirm_skip', False) and self._appear_click_center(self.O_STORY_CONFIRM_SKIP):
            self._can_confirm_skip = False
            # 点完「确认跳过」后接续出现「底部跳过」→ 进入待命
            self._arm_bottom_skip()
            return 1

        # ---- 底部「跳过」（对话后出现，OCR 容错过读）：仅在待命窗口内识别，点即消耗；窗口内未出现则放弃 ----
        if getattr(self, '_can_bottom_skip', False):
            if time.time() > self._bottom_skip_deadline:
                self._can_bottom_skip = False
            elif self._ocr_contains_click(self.O_STORY_SKIP, "跳过"):
                self._can_bottom_skip = False
                return 1

        # ---- 剧情对话徽章（"⋯"/"?"）：位置稳定后再点，避免过场/运镜移动时误点 ----
        # 点击「三点」进入/推进剧情 → 底部「跳过」识别进入待命
        if self._stable_center_click(self.I_STORY_DIALOG_DOTS):
            self._arm_bottom_skip()
            return 1
        # 点击「问号」才触发对话 → 底部「跳过」识别进入待命
        if self._stable_center_click(self.I_STORY_DIALOG_QUESTION):
            self._arm_bottom_skip()
            return 1
        # 点击眼睛后也会出现「底部跳过」→ 底部跳过进入待命
        if self._appear_click_center(self.I_STORY_DIALOG_EYE, interval=0.8):
            self._arm_bottom_skip()
            return 1

        # ---- 右上角跳过按钮（过场动画）：点击后待命「确认跳过」，
        #      放最低优先级，避免在对话界面误抢三点 ----
        if self._appear_click_center(self.I_STORY_SKIP_RIGHT, interval=0.8):
            self._can_confirm_skip = True
            return 1

        return 0


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()
    t.run()
