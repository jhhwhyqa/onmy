# This Python file uses the following encoding: utf-8
"""秘闻副本 - 低层速刷。

秘闻选择页每张卡片的副标题形如「壹·月明」，其中「壹」代表该秘闻**当前停留的层数**
（未挑战过 = 壹，已通到第 3 层 = 叁）。本任务只挑还停在「壹」（没打过）的秘闻：

1. 在选择页找显示「壹」的卡片 -> 点它选中 -> 点「进入」进入详情页；
2. 详情页先看层数列表里**最近的未解锁层**：超过配置的 ``max_layer`` 就直接退出
   （见 :meth:`ScriptTask.nearest_locked_layer`）；
3. 否则从当前层往上打，打到**失败**或打满 ``max_layer`` 次为止；
4. 退出详情页 -> 回到列表 -> 继续向下滑动找下一个「壹」。

打过之后卡片副标题不再是「壹」，所以「找壹」天然跳过了已完成的秘闻，无需维护进度。

踩过的坑（``merge_area`` 语义错位、列表滚动导致点错、``O_LAYER_1`` roi 右边界）
详见 ``.agents/memory/`` 里 EasySecret 的笔记，代码里不再重复。
"""

import re
import time

import numpy as np

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.EasySecret.assets import EasySecretAssets
from tasks.EasySecret.config import EasySecret
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.game_ui import GameUi
from tasks.GlobalGame.assets import GlobalGameAssets
import tasks.EasySecret.page as pages


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, EasySecretAssets):
    """秘闻副本 低层速刷"""

    conf: EasySecret = None

    # 回到选择页后连续滑动这么多次仍找不到「壹」-> 认为已到底，结束
    max_scroll = 10
    # 连续进入失败这么多次 -> 结束（每次会换一个候选点击点重试）
    enter_fail_limit = 5
    # 连续「进去了却一场没打」这么多次 -> 结束（battle_limit=0 时唯一的兜底）
    skip_limit = 10
    # 点「挑战」后等进入战斗页的最长时间（秒）；剧情对话可能要点很多次
    battle_enter_timeout = 60
    # 秘闻列表所在的画面区域 (x1, y1, x2, y2)，用来判断列表有没有还在滚动
    list_area = (110, 140, 795, 655)
    # 相邻两次截图在该区域的平均像素差小于这个值 -> 认为列表已经停稳
    list_stable_threshold = 0.8
    # 等列表停稳的最长时间（秒）
    list_stable_timeout = 4
    # 层数汉字 -> 数字（OCR 偶尔把大写读成简体，两套都认）
    LAYER_NUMERALS = {
        '壹': 1,
        '贰': 2,
        '叁': 3,
        '肆': 4,
        '伍': 5,
        '陆': 6,
        '柒': 7,
        '捌': 8,
        '一': 1,
        '二': 2,
        '三': 3,
        '四': 4,
        '五': 5,
        '六': 6,
        '七': 7,
        '八': 8,
    }
    # 详情页层数列表里「这一层还没解锁」的标记文本
    locked_text = '未解锁'

    def run(self):
        self.conf = self.config.easy_secret
        self.switch_soul()
        self.goto_page(pages.page_secret_zones)
        success = self.run_easy_secret()
        self.goto_page(pages.page_main)
        self.set_next_run(task='EasySecret', success=success, finish=success)
        raise TaskEnd

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #

    def run_easy_secret(self) -> bool:
        """遍历秘闻列表，逐个速刷低层。

        Returns:
            bool: True  = 正常跑完（列表已无未挑战秘闻 / 达到挑战次数上限）；
                  False = 中途异常，按 failure_interval 重试。
        """
        logger.hr('EasySecret battle', 2)
        battle_limit = self.conf.easy_secret_config.battle_limit
        battle_count = 0
        scroll_count = 0
        enter_fail = 0
        skip_streak = 0

        while True:
            if battle_limit > 0 and battle_count >= battle_limit:
                logger.info(f'Reach battle limit [{battle_limit}], exit')
                return True

            self.screenshot()

            # --- 详情页：已经进入某个秘闻 ---
            if self.appear(EasySecretAssets.I_ES_FIRE):
                remain = battle_limit - battle_count if battle_limit > 0 else -1
                battles = self.run_one_secret(remain)
                battle_count += battles
                enter_fail = 0
                # 进去了却一场没打（在跳过名单里 / 最近的未解锁层太深）时计数，
                # 连续太多次说明列表状态和实际对不上，再点也是白点，直接结束。
                if battles == 0:
                    skip_streak += 1
                    if skip_streak >= self.skip_limit:
                        logger.warning(
                            f'{self.skip_limit} secrets skipped in a row, '
                            f'the secret list looks inconsistent, exit'
                        )
                        return False
                else:
                    skip_streak = 0
                if not self.exit_secret():
                    logger.warning('Cannot exit secret, stop this run')
                    return False
                # 回到秘闻主界面 -> 滑动计数清零，从当前位置重新往下找
                scroll_count = 0
                continue

            # --- 选择页：找还停在「壹」的秘闻 ---
            if self.appear(EasySecretAssets.I_CHECK_SECRET):
                # 刚切页 / 刚滑完，列表可能还在滚，先等它停稳再取坐标
                self.wait_list_stable()
                card = self.find_layer_1_card(enter_fail)
                if card is not None:
                    name, x, y, text = card
                    logger.info(
                        f'Find un-challenged secret [{text}] name=[{name}] -> click ({x}, {y})'
                    )
                    self.device.click(
                        x=x, y=y, control_name=EasySecretAssets.O_LAYER_1.name
                    )
                    self.device.click_record_clear()
                    time.sleep(0.6)
                    if self.enter_secret_detail(name):
                        enter_fail = 0
                        continue
                    enter_fail += 1
                    if enter_fail >= self.enter_fail_limit:
                        logger.warning('Failed to enter secret repeatedly, exit')
                        return False
                    # 进错秘闻时 enter_secret_detail 已经退回列表；没进去时本来就
                    # 还在列表上。这里统一再兜一次，确保下一次循环是在选择页。
                    if not self.exit_secret():
                        logger.warning(
                            'Cannot go back to the secret list, stop this run'
                        )
                        return False
                    continue

                # 本屏没有「壹」-> 向下滑动继续找
                if scroll_count >= self.max_scroll:
                    logger.info('Reach the bottom of the secret list, exit')
                    return True

                if self.swipe(EasySecretAssets.S_ES_SWIPE_DOWN, interval=1):
                    self.device.click_record_clear()
                    scroll_count += 1
                time.sleep(0.4)
                continue

            # --- 未知页面：只等，不乱跳 ---
            time.sleep(0.2)

    # ------------------------------------------------------------------ #
    # 选择页
    # ------------------------------------------------------------------ #

    def _list_crop(self):
        """裁出秘闻列表区域，用于判断列表有没有在滚动。"""
        x1, y1, x2, y2 = self.list_area
        return self.device.image[y1:y2, x1:x2]

    @staticmethod
    def _mean_diff(image1, image2) -> float:
        """两张同尺寸图（或 None）的平均像素差。"""
        if image1 is None or image2 is None or image1.shape != image2.shape:
            return 255.0
        diff = np.abs(image1.astype(np.int16) - image2.astype(np.int16))
        return float(diff.mean())

    def wait_list_stable(self) -> bool:
        """等秘闻列表停止滚动。

        Returns:
            bool: True = 画面已停稳；False = 超时仍在动（调用方自行决定怎么处理）。
        """
        timer = Timer(self.list_stable_timeout).start()
        previous = None
        stable = 0
        while True:
            self.screenshot()
            current = self._list_crop()
            if (
                previous is not None
                and self._mean_diff(previous, current) < self.list_stable_threshold
            ):
                # 连续两帧都没动才算停稳（避免刚好卡在惯性里的一次短暂停顿上）
                stable += 1
                if stable >= 2:
                    return True
            else:
                stable = 0
            if timer.reached():
                logger.warning(
                    f'Secret list still moving after {self.list_stable_timeout}s'
                )
                return False
            previous = current
            time.sleep(0.3)

    def find_layer_1_card(self, attempt: int = 0):
        """在选择页上找第一个还停在「壹」（未挑战）的秘闻卡片。

        Args:
            attempt: 第几次尝试。用来在候选点之间轮换 —— 万一点下去游戏没响应，
                下一次换个点再试（而不是在同一个点上反复撞）。

        跳过名单里的秘闻（见 ``skip_secrets``）在这里就被丢掉，连点都不点 ——
        否则「进去 -> 跳过 -> 退出来」会反复撞上同一张卡，把 ``skip_limit`` 攒满
        直接判任务失败。

        Returns:
            tuple[str, int, int, str] | None:
                ``(卡片名字, 点击 x, 点击 y, 命中的「壹」文本)``；没有可点的「壹」时 None。
        """
        rule = EasySecretAssets.O_LAYER_1
        results = rule.detect_and_ocr(self.device.image, logDisplay=False)
        if not results:
            return None
        indices = rule.filter(results)
        if not indices:
            return None

        # detect_and_ocr 返回的 box 是**相对 roi** 的，这里统一转成全屏坐标
        roi_x, roi_y = rule.roi[0], rule.roi[1]
        boxes = []
        for result in results:
            box = np.array(result.box).astype(int)
            boxes.append(
                (
                    int(box[0, 0]) + roi_x,
                    int(box[0, 1]) + roi_y,
                    int(box[1, 0] - box[0, 0]),
                    int(box[2, 1] - box[0, 1]),
                    result.ocr_text,
                )
            )

        # 每个「壹」框配一个「正上方（0 < dy < 60）且横向有重叠」的名字行
        candidates = []
        for index in indices:
            lx, ly, lw, lh, text = boxes[index]
            name = ''
            name_box = None
            for bx, by, bw, bh, btext in boxes:
                if bx + bw < lx or bx > lx + lw:
                    continue
                if 0 < ly - by < 60 and (name_box is None or by > name_box[1]):
                    name = btext
                    name_box = (bx, by, bw, bh)
            # 名字读不出来时不敢乱丢（宁可进去后用详情页标题再判一次）
            if name and self.should_skip(name):
                logger.info(f'Ignore skipped secret [{name}]')
                continue
            candidates.append((name, lx, ly, lw, lh, name_box, text))

        if not candidates:
            return None
        name, lx, ly, lw, lh, name_box, text = candidates[0]

        # 候选点击点，全部落在卡片内部（层数行 / 名字行 / 两行之间）
        points = [(lx + lw // 2, ly + lh // 2)]
        if name_box is not None:
            nx, ny, nw, nh = name_box
            points.append((nx + nw // 2, ny + nh // 2))
            points.append((lx + lw // 2, (ly + ny + nh) // 2))
        x, y = points[attempt % len(points)]
        return name, x, y, text

    def enter_secret_detail(self, expected: str = '') -> bool:
        """点「进入」，并确认进入的是**目标**秘闻的详情页。

        调用前应已点中某张「壹」卡片。

        Args:
            expected: 目标卡片上 OCR 到的秘闻名。用于进入后核对 —— 卡片点击
                没生效时，游戏会进入**上一次选中**的那个秘闻。

        Returns:
            bool: True 表示已确认进入目标秘闻的详情页。
        """
        time.sleep(0.6)  # 等右侧预览刷新
        self.screenshot()
        # 有些情况下点卡片就直接进了详情页
        if self.appear(EasySecretAssets.I_ES_FIRE):
            return True

        if not self.appear_then_click(EasySecretAssets.I_ES_ENTER, interval=1.2):
            logger.warning('Enter button not found')
            return False
        time.sleep(1.2)  # 进入详情页的动画
        self.screenshot()
        if not self.appear(EasySecretAssets.I_ES_FIRE):
            logger.warning('Enter secret failed')
            return False

        # 核对标题，避免「点空了 -> 进了上一次选中的秘闻」
        if expected:
            title = str(
                EasySecretAssets.O_SECRET_TITLE.ocr(self.device.image, log=False)
            ).strip()
            if not self._same_secret(expected, title):
                logger.warning(f'Entered [{title}] but expected [{expected}], go back')
                self.exit_secret()
                return False
        return True

    @staticmethod
    def _same_secret(expected: str, actual: str) -> bool:
        """宽松比较两个秘闻名。

        同一张卡片的名字行和详情页标题会被 OCR 成**不同的错字**
        （实测 `幽悟引晚` vs `幽潘引晚`，实际是「幽幡引魂」），所以按共同汉字占比判断，
        只有几乎没有任何共同字（明显是另一个秘闻）才算进错。
        """

        def chinese(text: str) -> str:
            return re.sub(r'[^\u4e00-\u9fff]', '', text or '')

        want, got = chinese(expected), chinese(actual)
        # 名字行一般 4 个字；太短说明 OCR 只读出了残字，别拿它当依据
        if len(want) < 3 or not got:
            return True
        common = len(set(want) & set(got))
        return common / len(set(want)) >= 0.34

    # ------------------------------------------------------------------ #
    # 详情页
    # ------------------------------------------------------------------ #

    @classmethod
    def _parse_layer_number(cls, text: str) -> int:
        """从「贰·渐沉」这类层数名里取出层数，取不到返回 0。

        只看**前 3 个字符** —— OCR 会在前面多带噪声字符（实测 `②壹·入梦` / `@叁·迷津`），
        看多了会误吃名字里的字。
        """
        for char in (text or '')[:3]:
            if char in cls.LAYER_NUMERALS:
                return cls.LAYER_NUMERALS[char]
        return 0

    def nearest_locked_layer(self) -> int:
        """读详情页左侧层数列表，返回**最近的未解锁层**是第几层。

        Returns:
            int: 1-8；读不出来（OCR 没命中 / 列表没滚到）返回 0。
        """
        rule = EasySecretAssets.O_LAYER_LIST
        results = rule.detect_and_ocr(self.device.image, logDisplay=False)
        if not results:
            return 0

        # detect_and_ocr 的 box 是相对 roi 的，统一转成全屏 y
        roi_y = rule.roi[1]
        boxes = []
        for result in results:
            box = np.array(result.box).astype(int)
            boxes.append((int(box[0, 1]) + roi_y, result.ocr_text))

        locked_ys = [by for by, text in boxes if self.locked_text in text]
        if not locked_ys:
            return 0
        lock_y = min(locked_ys)  # 最上面的那一行「未解锁」= 最近的未解锁层

        best_y, layer = -1, 0
        for by, text in boxes:
            if self.locked_text in text:
                continue
            if not 0 < lock_y - by < 110:
                continue
            number = self._parse_layer_number(text)
            if number and by > best_y:
                best_y, layer = by, number
        return layer

    def run_one_secret(self, remain: int) -> int:
        """在当前秘闻详情页挑战，直到失败或达到层数上限。

        Args:
            remain: 本次运行还剩多少次挑战额度；小于 0 表示不限制。

        Returns:
            int: 本次实际发起的战斗次数。
        """
        conf = self.conf.easy_secret_config
        title = str(
            EasySecretAssets.O_SECRET_TITLE.ocr(self.device.image, log=False)
        ).strip()
        logger.info(f'Enter secret [{title}]')
        if self.should_skip(title):
            logger.info(f'Skip high difficulty secret [{title}]')
            return 0

        # 最近的未解锁层已经超过配置的最大层数 -> 这个秘闻打过头了，不再挑战，
        # 直接退出去找下一个（返回 0 后调用方会 exit_secret() 回选择页）。
        nearest = self.nearest_locked_layer()
        if nearest == 0:
            # 读不出来（列表没滚到 / OCR 漏了）就不拦，宁可多打一次也别卡死
            logger.warning('Cannot read the layer list, challenge anyway')
        elif nearest > conf.max_layer:
            logger.info(
                f'Nearest locked layer is {nearest} '
                f'(> max_layer {conf.max_layer}), skip [{title}]'
            )
            return 0

        count = 0
        for layer in range(1, conf.max_layer + 1):
            if 0 <= remain <= count:
                logger.info('Reach the remaining battle limit, stop this secret')
                break
            self.screenshot()
            if not self.appear(EasySecretAssets.I_ES_FIRE):
                break
            if not self.click_until_battle():
                logger.warning(
                    f'Cannot start battle at layer {layer}, stop this secret'
                )
                break

            win = self.run_general_battle(
                config=self.conf.general_battle_config,
                battle_key='easy_secret',
                exit_matcher=pages.page_easy_secret_detail,
            )
            count += 1
            # 战斗结束后可能还压着剧情对话，先点掉再判断胜负 / 继续下一层
            self.back_to_secret_detail()
            if not win:
                logger.info(f'Battle lost at layer {layer}, stop this secret')
                break
            logger.info(f'Layer {layer} cleared')
        return count

    def back_to_secret_detail(self, timeout: float = 45) -> bool:
        """战斗结束后把剧情对话点掉，直到重新看到「挑战」按钮。

        Returns:
            bool: True = 已重新看到「挑战」，或已退回选择页。
        """
        timer = Timer(timeout).start()
        while True:
            self.screenshot()
            # 目标：重新看到「挑战」
            if self.appear(EasySecretAssets.I_ES_FIRE):
                return True
            # 兜底：有些情况会直接退回选择页（例如最后一层打完）
            if self.appear(EasySecretAssets.I_CHECK_SECRET):
                return True
            if timer.reached():
                logger.warning(f'Story dialogue not finished in {timeout}s, give up')
                return False
            if self._advance_story_or_dialog():
                continue
            # 兜底：过场黑屏之类识别不到任何东西时，点左侧安全空白区
            self.click(random_click(ltrb=(True, False, False, False)), interval=0.6)
            self.device.click_record_clear()

    def _advance_story_or_dialog(self) -> bool:
        """尝试推进一次剧情对话 / 点掉一个确认弹窗。

        Returns:
            bool: True = 本次做了动作，调用方应 ``continue`` 重新截图。
        """
        # 确认弹窗（体力不足 / 退出确认 / 奖励确认等）—— 任何页面都该点掉
        if self.appear_then_click(GlobalGameAssets.I_UI_CONFIRM_SAMLL, interval=1):
            self.device.click_record_clear()
            return True
        if self.appear_then_click(GlobalGameAssets.I_UI_CONFIRM, interval=1):
            self.device.click_record_clear()
            return True
        # 「挑战」可见 -> 没有对话压着，不该在这里点
        if self.appear(EasySecretAssets.I_ES_FIRE):
            return False
        if self.appear(GlobalGameAssets.I_UI_BACK_RED):
            # 红叉在、但「挑战」看不到 -> 详情页被剧情对话盖住了，点中央推进
            self.click(GlobalGameAssets.I_CHAT_CLOSE_BUTTON, interval=0.6)
            self.device.click_record_clear()
            return True
        return False

    def click_until_battle(self) -> bool:
        """点击「挑战」并一路清掉剧情对话，直到确认进入战斗页面。

        Returns:
            bool: True = 已确认在准备/战斗页；False = 超时仍未进入。
        """
        timer = Timer(self.battle_enter_timeout)
        timer.start()
        while True:
            self.screenshot()
            # 正向判据：确认已经进入准备/战斗页
            if self.is_in_battle(False):
                return True
            if timer.reached():
                logger.warning(
                    f'Cannot enter battle in {self.battle_enter_timeout}s, give up'
                )
                return False
            # 还在详情页（能看到「挑战」）-> 点挑战
            if self.appear_then_click(EasySecretAssets.I_ES_FIRE, interval=1):
                self.device.click_record_clear()
                continue
            # 剧情对话 / 确认弹窗
            if self._advance_story_or_dialog():
                continue
            # 兜底：点左侧安全空白区
            self.click(random_click(ltrb=(True, False, False, False)), interval=0.6)
            self.device.click_record_clear()

    def exit_secret(self, timeout: float = 45) -> bool:
        """从详情页（可能还压着剧情对话）一路点到秘闻选择页。

        顺序：先清剧情对话 / 确认弹窗 -> 再点右上角红叉退出。
        注意这里不要给 ``appear`` 传 interval —— 它会在未到间隔时直接返回 False，
        哪怕目标已经出现，会把「已回到选择页」漏判。

        Returns:
            bool: True = 已回到选择页。
        """
        timer = Timer(timeout).start()
        while True:
            self.screenshot()
            if self.appear(EasySecretAssets.I_CHECK_SECRET):
                return True
            if timer.reached():
                logger.warning('Exit secret failed')
                return False
            if self._advance_story_or_dialog():
                continue
            if self.appear_then_click(GlobalGameAssets.I_UI_BACK_RED, interval=0.8):
                continue
            # 兜底：点左侧安全空白区
            self.click(random_click(ltrb=(True, False, False, False)), interval=0.6)
            self.device.click_record_clear()

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #

    def skip_secrets(self) -> list:
        """解析配置里需要跳过的秘闻标题列表。"""
        raw = self.conf.easy_secret_config.skip_secrets or ''
        return [name.strip() for name in re.split(r'[,，\n]', raw) if name.strip()]

    def should_skip(self, title: str) -> bool:
        """标题是否命中跳过名单（容忍 OCR 丢字 / 带噪声字符）。

        OCR 实测把「呱士无双」读成「士无双」（丢首字）、把「花赠我心人」读成
        「。花赠我心人！」（带噪声），所以先试子串，再按**汉字重合度**兜底。
        """
        if not title:
            return False
        title_chars = set(re.sub(r'[^\u4e00-\u9fff]', '', title))
        if not title_chars:
            return False
        for name in self.skip_secrets():
            if name in title:
                return True
            name_chars = set(name)
            if len(name_chars & title_chars) / len(name_chars) >= 0.6:
                return True
        return False

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
