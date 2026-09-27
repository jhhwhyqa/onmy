"""协同对弈：每人初选五人，再从己方卡牌中安排三人上场。"""

import re
import time
from pathlib import Path

import cv2
import numpy as np

from module.exception import GameStuckError, TaskEnd
from module.logger import logger
from tasks.DraftDuel.assets import DraftDuelAssets
from tasks.DraftDuel.config import DraftMatchMode
from tasks.DraftDuel.strategy import CATALOG, choose_pick, normalize_name, plan_lineup
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_town


class ScriptTask(GameUi, DraftDuelAssets):
    TEAM_SIZE = 5

    # assets.py 由 dev_tools/assets_extract.py 从 res/*.json 生成，只产出扁平条目；
    # 同屏多位置资源的组合关系在此声明，代码里照旧按下标取用。
    O_NAMES = (DraftDuelAssets.O_DRAFT_LEFT_NAME, DraftDuelAssets.O_DRAFT_MIDDLE_NAME,
               DraftDuelAssets.O_DRAFT_RIGHT_NAME)
    C_SELECT = (DraftDuelAssets.C_DRAFT_LEFT_SELECT, DraftDuelAssets.C_DRAFT_MIDDLE_SELECT,
                DraftDuelAssets.C_DRAFT_RIGHT_SELECT)
    C_DETAIL_CARDS = (DraftDuelAssets.C_BATTLE_DETAIL_0, DraftDuelAssets.C_BATTLE_DETAIL_1,
                      DraftDuelAssets.C_BATTLE_DETAIL_2, DraftDuelAssets.C_BATTLE_DETAIL_3,
                      DraftDuelAssets.C_BATTLE_DETAIL_4, DraftDuelAssets.C_BATTLE_DETAIL_5)
    O_LINEUP_NAMES = (DraftDuelAssets.O_LINEUP_NAME_0, DraftDuelAssets.O_LINEUP_NAME_1,
                      DraftDuelAssets.O_LINEUP_NAME_2, DraftDuelAssets.O_LINEUP_NAME_3,
                      DraftDuelAssets.O_LINEUP_NAME_4)
    O_LINEUP_SPEEDS = (DraftDuelAssets.O_LINEUP_SPEED_0, DraftDuelAssets.O_LINEUP_SPEED_1,
                       DraftDuelAssets.O_LINEUP_SPEED_2, DraftDuelAssets.O_LINEUP_SPEED_3,
                       DraftDuelAssets.O_LINEUP_SPEED_4)
    O_LINEUP_DEFENSES = (DraftDuelAssets.O_LINEUP_DEFENSE_0, DraftDuelAssets.O_LINEUP_DEFENSE_1,
                         DraftDuelAssets.O_LINEUP_DEFENSE_2, DraftDuelAssets.O_LINEUP_DEFENSE_3,
                         DraftDuelAssets.O_LINEUP_DEFENSE_4)

    CROSS_TEMPLATE = cv2.Canny(cv2.imdecode(
        np.fromfile(str(Path(__file__).with_name('selected_cross.png')), np.uint8),
        cv2.IMREAD_COLOR), 60, 130)

    @classmethod
    def _selected_cross(cls, image):
        """返回整排卡牌中叉号的屏幕横坐标与匹配分数。"""
        roi = cv2.Canny(image[500:550, 240:850], 60, 130)
        _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(
            roi, cls.CROSS_TEMPLATE, cv2.TM_CCOEFF_NORMED))
        return 240 + point[0] + cls.CROSS_TEMPLATE.shape[1] // 2, float(score)

    @classmethod
    def _selected_cards(cls, image):
        """检测卡面上的白色交叉标记；已灰化卡没有此标记。"""
        result = set()
        for index, x in enumerate((320, 435, 550, 665, 780)):
            roi = cv2.Canny(image[502:547, x-26:x+26], 60, 130)
            score = float(cv2.matchTemplate(
                roi, cls.CROSS_TEMPLATE, cv2.TM_CCOEFF_NORMED).max())
            if score >= 0.5:
                result.add(index)
        return result

    def _enter_first_round(self, settings):
        self.goto_page(page_town)
        self.screenshot()
        self.click(self.I_TOWN_GOTO_DRAFT_DUEL, interval=0.6)
        self.screenshot()
        if settings.match_mode == DraftMatchMode.TEAM:
            deadline = time.monotonic() + settings.teammate_timeout_seconds
            teammate_seen = 0
            while time.monotonic() < deadline:
                self.device.stuck_record_clear()
                self.screenshot()
                if not self.appear(self.I_EMPTY_TEAMMATE):
                    teammate_seen += 1
                    if teammate_seen >= 3:
                        break
                else:
                    teammate_seen = 0
                time.sleep(0.8)
            else:
                raise GameStuckError('协同对弈组队模式等待队友超时')
        logger.info(f'DraftDuel matchmaking mode: {settings.match_mode.value}')
        self._start_first_round(settings)

    def _wait_lobby_ready(self, timeout) -> bool:
        """等大厅的「战」按钮出现（用按钮图片判断，不看按钮文字）。

        :param timeout: 最长等待秒数
        :return: 出现「战」按钮返回 True；一直是「等待」或还没加载完返回 False
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.device.stuck_record_clear()
            self.screenshot()
            if self.appear(self.I_DRAFT_START):
                return True
            time.sleep(0.5)
        return False

    def _start_first_round(self, settings):
        """点大厅的「战」开始匹配，并校验点击是否生效。

        实测「战」偶尔点了没反应：画面停在组队大厅，`O_DRAFT_ROUND` 框里读到的是
        频道聊天（「60队」之类），脚本傻等到超时才报错。所以这里：

        - 用「战」按钮的图片（`I_DRAFT_START`）判断能不能点：匹配不到就不点
          （大厅还在加载，或已经进入「等待」状态），等下一轮再看；
        - 点完在窗口内校验是否出现「请选择第N名式神」，没进展就重试，最多三次；
        - 三次都没生效才回落到 `start_timeout_seconds` 的长等待，并留下点击次数日志。

        组队模式的队友等待在 `_enter_first_round` 里已完成。
        """
        confirm_seconds = 6
        clicked = 0
        for attempt in range(1, 4):
            if not self._wait_lobby_ready(confirm_seconds):
                logger.info(f'DraftDuel 战 button not visible before attempt {attempt}/3; '
                            f'lobby is loading or already waiting')
                continue
            clicked += 1
            logger.info(f'DraftDuel click 战 (attempt {attempt}/3)')
            self.click(self.I_DRAFT_START, interval=0.5)
            deadline = time.monotonic() + confirm_seconds
            while time.monotonic() < deadline:
                self.device.stuck_record_clear()
                self.screenshot()
                if self._round_number() == 1:
                    return
                time.sleep(0.4)
        logger.info(f'DraftDuel clicked 战 {clicked} time(s); keep waiting for the draft prompt '
                    f'up to {settings.start_timeout_seconds}s')
        self._wait_round(1, settings.start_timeout_seconds)

    def _round_text(self) -> str:
        """读取轮次提示的原文本（如「请选择第1名式神」）。"""
        return str(self.O_DRAFT_ROUND.ocr(self.device.image) or '')

    def _round_number(self, text: str = None):
        if text is None:
            text = self._round_text()
        match = re.search(r'第\s*([1-5])\s*名\s*式神', text)
        return int(match.group(1)) if match else None

    def _wait_round(self, expected, timeout):
        deadline = time.monotonic() + timeout
        last_text = ''
        while time.monotonic() < deadline:
            self.device.stuck_record_clear()
            self.screenshot()
            text = self._round_text()
            if text:
                last_text = text
            number = self._round_number(text)
            if number == expected:
                return
            if number is not None and number > expected:
                raise GameStuckError(
                    f'协同对弈轮次跳过：期望第{expected}轮，实际第{number}轮')
            time.sleep(0.5)
        # 带上现场信息：框里最后读到什么、大厅「战」按钮是否还在，方便下次定位卡在哪一步
        raise GameStuckError(
            f'协同对弈等待第{expected}轮超时；'
            f'轮次框最后识别到 {last_text!r}，'
            f'大厅「战」按钮可见={self.appear(self.I_DRAFT_START)}')

    def _offers(self):
        for attempt in range(2):
            raw = [str(rule.ocr(self.device.image) or '') for rule in self.O_NAMES]
            names = [normalize_name(value) for value in raw]
            logger.info(f'DraftDuel offers: raw={raw}, names={names}')
            if len([name for name in names if name]) >= 2:
                return names
            if attempt == 0:
                self.screenshot()
        raise GameStuckError('协同对弈至少两张候选卡名称未能识别')

    def _wait_final_pick_accepted(self, timeout):
        deadline = time.monotonic() + timeout
        absent_since = None
        while time.monotonic() < deadline:
            self.device.stuck_record_clear()
            self.screenshot()
            if self._round_number() != self.TEAM_SIZE:
                absent_since = absent_since or time.monotonic()
                if time.monotonic() - absent_since >= 2:
                    return
            else:
                absent_since = None
            time.sleep(0.5)
        raise GameStuckError('协同对弈第五次选择后未离开选人界面')

    def _battle_ready(self):
        return '确定' in str(self.O_BATTLE_CONFIRM.ocr(self.device.image) or '')

    def _read_battle_lineup(self, drafted):
        """阵容详情依当前卡牌顺序列出五人；用初选名单核对 OCR。"""
        candidates = []
        for index, x in enumerate((115, 190, 265, 335, 405, 480)):
            roi = self.device.image[40:90, x-24:x+24]
            saturation = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)[:, :, 1].mean()
            candidates.append((saturation >= 120, -float(roi.std()), index))
        opened = False
        for _, _, index in sorted(candidates):
            self.click(self.C_DETAIL_CARDS[index], interval=0.15)
            self.screenshot()
            if '阵容详情' in str(self.O_DETAIL_TITLE.ocr(self.device.image) or ''):
                opened = True
                break
        if not opened:
            logger.warning('DraftDuel lineup detail did not open')
            return None
        try:
            self.click(self.C_DETAIL_MINE, interval=0.3)
            self.screenshot()
            names = [normalize_name(str(rule.ocr(self.device.image) or ''))
                     for rule in self.O_LINEUP_NAMES]
            missing = set(drafted) - set(name for name in names if name)
            if len(missing) == 1 and names.count(None) == 1:
                names[names.index(None)] = missing.pop()
            if set(names) != set(drafted) or len(set(names)) != 5:
                logger.warning(f'DraftDuel battle lineup OCR mismatch: {names} vs {drafted}')
                return None
            speed_by_name = {}
            for index, name in enumerate(names):
                label = CATALOG[name].tier
                if '速' in label or '220' in label or '170' in label:
                    raw = str(self.O_LINEUP_SPEEDS[index].ocr(self.device.image) or '')
                    match = re.search(r'\d{2,3}', raw)
                    if match:
                        speed_by_name[name] = int(match.group())
            defense_by_name = {}
            for index, name in enumerate(names):
                if name == '云外镜':
                    raw = str(self.O_LINEUP_DEFENSES[index].ocr(self.device.image) or '')
                    match = re.search(r'\d{3,4}', raw)
                    if match:
                        defense_by_name[name] = int(match.group())
            logger.info(f'DraftDuel battle lineup: {names}, '
                        f'speed={speed_by_name}, defense={defense_by_name}')
            return names, speed_by_name, defense_by_name
        finally:
            self.click(self.C_DETAIL_CLOSE, interval=0.2)

    @staticmethod
    def _card_saturation(image, index):
        x = (320, 435, 550, 665, 780)[index]
        hsv = cv2.cvtColor(image[548:620, x-35:x+35], cv2.COLOR_BGR2HSV)
        return float(hsv[:, :, 1].mean())

    @staticmethod
    def _spotlight_x(image):
        """寻找当前候选式神上方的蓝色聚光灯；灯位随上场轮次移动。"""
        area = image[130:300, 80:900].astype(np.float32)
        blue = (area[:, :, 2] > 130) & (area[:, :, 2] > area[:, :, 0] * 1.15)
        columns = blue.sum(axis=0).astype(np.float32)
        window = np.convolve(columns, np.ones(60, dtype=np.float32), mode='valid')
        return int(80 + np.argmax(window) + 30)

    def _select_battle_lineup(self, drafted):
        detail = getattr(self, '_battle_detail', None)
        if detail is None:
            detail = self._read_battle_lineup(drafted)
            if detail is not None:
                self._battle_detail = detail
        if detail is None:
            return
        names, speeds, defenses = detail
        self.screenshot()
        if not self._battle_ready():
            return
        baseline = getattr(self, '_card_color_baseline', {})
        if not baseline:
            baseline = {name: self._card_saturation(self.device.image, index)
                        for index, name in enumerate(names)}
            self._card_color_baseline = baseline
        locked = getattr(self, '_battle_locked', [])
        for turn in range(3):
            self.screenshot()
            if not self._battle_ready():
                return
            pending = self._selected_cards(self.device.image)
            available = []
            for index, name in enumerate(names):
                saturation = self._card_saturation(self.device.image, index)
                original = baseline.get(name, saturation)
                grey = saturation < original * 0.75 and original - saturation > 8
                if not grey or name in locked:
                    available.append(name)
            if len(available) < 3:
                logger.warning(f'DraftDuel not enough active cards: {available}')
                return
            preferred = getattr(self, '_battle_plan', None)
            if preferred is None:
                try:
                    preferred = plan_lineup(available, team_size=3, locked=locked,
                                            speeds=speeds, defenses=defenses)
                except ValueError as exc:
                    logger.warning(f'DraftDuel lineup planning failed: {exc}')
                    return
                self._battle_plan = preferred
            targets = [name for name in preferred if name not in locked]
            pending_targets = [names[index] for index in pending
                               if names[index] in targets]
            target = pending_targets[0] if pending_targets else targets[0]
            index = names.index(target)
            if index not in pending:
                before = self.device.image.copy()
                before_x, _ = self._selected_cross(before)
                spotlight_x = self._spotlight_x(before)
                self.device.swipe(
                    p1=((320, 435, 550, 665, 780)[index], 595),
                    p2=(spotlight_x, 320), duration=(0.4, 0.5),
                    control_name='draft_battle_field')
                time.sleep(0.3)
                self.screenshot()
                cross_x, cross_score = self._selected_cross(self.device.image)
                portrait_change = float(np.abs(
                    before[35:95, 85:510].astype(np.int16) -
                    self.device.image[35:95, 85:510].astype(np.int16)).mean())
                if (cross_score < 0.46 or
                        abs(cross_x - (320, 435, 550, 665, 780)[index]) > 180 or
                        (abs(cross_x - before_x) < 35 and portrait_change < 6)):
                    logger.warning(
                        f'DraftDuel card not selected: {target}; '
                        f'spotlight={spotlight_x}, cross={before_x}->{cross_x} '
                        f'({cross_score:.2f}), '
                        f'portrait_change={portrait_change:.1f}')
                    return
            logger.info(f'DraftDuel field {len(locked) + 1}/3: {target}, '
                        f'planned={preferred}')
            self.click(self.C_BATTLE_CONFIRM, interval=0.3)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                self.screenshot()
                if not self._battle_ready() or index not in self._selected_cards(self.device.image):
                    locked.append(target)
                    self._battle_locked = locked
                    break
                time.sleep(0.3)
            else:
                logger.warning(f'DraftDuel confirmation not observed: {target}')
                return

    def _wait_battle_return(self, timeout, drafted):
        deadline = time.monotonic() + timeout
        active_preparation = False
        terminal_seen = 0
        while time.monotonic() < deadline:
            self.device.stuck_record_clear()
            self.screenshot()
            if self._battle_ready():
                if not active_preparation:
                    self._select_battle_lineup(drafted)
                    active_preparation = True
                time.sleep(0.5)
                continue
            active_preparation = False
            if len(getattr(self, '_battle_locked', [])) >= 3:
                self._battle_locked = []
                self._battle_plan = None
                self._battle_detail = None
            if '拒绝' in str(self.O_BOUNTY_REJECT.ocr(self.device.image) or ''):
                self.click(self.C_BOUNTY_REJECT, interval=0.3)
                continue
            if '取消' in str(self.O_FRIEND_CANCEL.ocr(self.device.image) or ''):
                self.click(self.C_FRIEND_CANCEL, interval=0.3)
                continue
            terminal_text = str(self.O_TERMINAL_RESULT.ocr(self.device.image) or '')
            if '番胜' in terminal_text and '终' in terminal_text:
                self.click(self.C_RESULT_CONTINUE, interval=0.4)
                continue
            if '点击屏幕继续' in str(self.O_RESULT_CONTINUE.ocr(self.device.image) or ''):
                self.click(self.C_RESULT_CONTINUE, interval=0.4)
                continue
            if self.appear(self.I_CHECK_TOWN) or self.appear(self.I_CHECK_MAIN):
                return
            score = str(self.O_LOBBY_SCORE.ocr(self.device.image) or '')
            match = re.search(r'([0-6])\s*番\s*胜', score)
            if '未开启' in score or match:
                if '未开启' in score:
                    terminal_seen += 1
                    if terminal_seen >= 2:
                        return
                    continue
                if match and int(match.group(1)) >= 6:
                    terminal_seen += 1
                    if terminal_seen >= 2:
                        return
                    continue
                terminal_seen = 0
                if match:
                    # 「0番胜」表示五人已选完的本局大厅；「未开启」才是新局入口。
                    self.click(self.C_RESULT_CONTINUE, interval=0.2)
                    self.screenshot()
                    # 用「战」按钮的图片判断能不能继续开战（「等待」状态匹配不到）
                    if self.appear(self.I_DRAFT_START):
                        self.click(self.I_DRAFT_START, interval=0.5)
                        logger.info(f'DraftDuel continuing same match at {score}')
            else:
                terminal_seen = 0
            time.sleep(2)
        raise GameStuckError('协同对弈对局结束后未返回可识别页面')

    def run(self):
        self.screenshot()
        settings = self.config.draft_duel.draft_duel_config
        if self._round_number() != 1:
            self._enter_first_round(settings)
        timeout = settings.pick_timeout_seconds
        team = []
        for round_number in range(1, self.TEAM_SIZE + 1):
            if round_number > 1:
                self._wait_round(round_number, timeout)
            # 对游戏内的十几秒倒计时只重试一次 OCR，避免耗尽选人时间。
            names = self._offers()
            decision = choose_pick(
                [name for name in names if name], team, team_size=self.TEAM_SIZE)
            position = names.index(decision.name)
            logger.info(
                f'DraftDuel pick {round_number}/{self.TEAM_SIZE}: '
                f'{decision.name}, score={decision.score}, '
                f'reasons={decision.reasons}, souls={decision.suggested_souls}'
            )
            self.click(self.C_SELECT[position], interval=0.5)
            team.append(decision.name)
        self._wait_final_pick_accepted(timeout)
        logger.info(f'DraftDuel five-pick lineup: {team}')
        self._wait_battle_return(settings.battle_timeout_seconds, team)
        self.set_next_run(task='DraftDuel', success=True, finish=True)
        raise TaskEnd('DraftDuel')
