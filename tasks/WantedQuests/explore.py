import re

from module.atom.gif import RuleGif
from module.atom.image import RuleImage
from module.logger import logger
from tasks.Exploration import page as pages
from tasks.Exploration.base import BaseExploration
from tasks.Exploration.config import UpType, UserStatus
from tasks.Exploration.script_task import ScriptTask as ExplorationScriptTask
from tasks.Exploration.version import HighLight
from typing import Optional


class ExploreWantedBoss(Exception):
    # 出现一种情况，要求的怪是仅仅最后的Boss，其他小怪不是
    pass


class WQExplore(ExplorationScriptTask, HighLight):
    _explor_cnt: int = 0  # 探索次数
    _max_cnt: int = 0  # 探索最大次数

    # 清图阶段: up=找高亮怪, left=回扫高亮怪左侧的小怪, right=向右清到 boss
    _wq_phase: str = 'up'
    _right_swipes: int = 0  # 找高亮怪时向右滑过的屏数
    _left_swipes: int = 0  # 回扫时已向左滑的次数
    _up_fought: bool = False
    _lock_checked: bool = False
    _wq_check_after_battle: bool = False  # 刚打完一场, 回到地图后检查悬赏进度
    _MAX_SWIPES = 12  # 单个方向最大滑动次数, 防止空转

    # 探索主界面的锁阵容图标: 已在 ExplorationAssets 注册
    # I_LOCK_OFF(未锁定时较暗的图标) / I_LOCK_ON(已锁定时较亮的图标),
    # 位置与其它副本准备页不同。

    def _default_detect_categories(self) -> set[str]:
        categories = super()._default_detect_categories()
        categories.add("exploration")
        return categories

    def search_up_fight(self, up_type: UpType = None) -> Optional[RuleImage | RuleGif]:
        # 优先打高亮怪
        if self.appear(self.TEMPLATE_GIF):
            self.fire_monster_type = 'wq_normal'
            return self.TEMPLATE_GIF
        # 找高亮怪的阶段不接普通怪; 高亮怪打完后继续清沿途小怪
        if self._wq_phase != 'up' and self.appear(self.I_NORMAL_BATTLE_BUTTON, interval=0.3):
            self.fire_monster_type = 'normal'
            return self.I_NORMAL_BATTLE_BUTTON
        return None

    def get_fire_button(self):
        # 先清高亮怪和小怪; 清完后遇到 boss 就直接挑战
        button = self.search_up_fight()
        if button is not None:
            return button
        if self._wq_phase != 'up' and self.appear(self.I_BOSS_BATTLE_BUTTON):
            self.fire_monster_type = 'boss'
            return self.I_BOSS_BATTLE_BUTTON
        return None

    def check_exit(self, current_page: pages.Page | None) -> bool:
        # 打完探索 boss 并回到探索主界面，本次探索才算完成
        if self.fire_monster_type == 'boss' and current_page == pages.page_exp_main:
            return True
        # 地图走到底且没有可打的怪时退出，避免空转
        return self.need_exit

    def _ensure_team_locked(self) -> bool:
        """在探索主界面检查并开启锁阵容。

        使用探索自己的锁图标(lock_on/lock_off)，与其它副本准备页位置不同。
        识别不到时打印警告并跳过，不会卡住战斗。
        :return: 本次是否点击过锁定按钮
        """
        clicked = False
        for _ in range(5):
            self.screenshot()
            if self.appear(self.I_LOCK_ON):  # 已锁定
                logger.info('Explore team is locked')
                return clicked
            if self.appear(self.I_LOCK_OFF):  # 未锁定, 点一下开启
                logger.info('Lock explore team')
                self.click(self.I_LOCK_OFF)
                clicked = True
                continue
            break
        logger.warning(
            'Explore team lock icon not recognized; skip locking. '
            'Check tasks/Exploration/res/lock_on.png and lock_off.png.'
        )
        return clicked

    def wq_count_enough(self) -> bool:
        """读取地图上的悬赏进度 y/x, 打满(y==x)时返回 True。"""
        text = self.O_WQ_TRACK_PROGRESS.ocr(self.device.image)
        matched = re.search(r'(\d+)\s*[7/]\s*(\d+)', str(text or ''))
        if not matched:
            return False
        current, required = int(matched.group(1)), int(matched.group(2))
        if required <= 0:
            return False
        logger.info(f'Wanted quest progress: {current}/{required}')
        return current >= required

    def run_on_exp_main(self):
        """高亮怪 → 回扫左侧小怪 → 向右清图直到 boss。"""
        if self._wq_check_after_battle:
            self._wq_check_after_battle = False
            if self.wq_count_enough():
                logger.info('Wanted quest finished, quit exploration')
                self.quit_exp_main()
                return
        if self.pre_page and self.pre_page != pages.page_exp_main:
            self.device.click_record_clear()
        if self.collect_reward():
            return
        if self.fire_monster_type == 'boss':
            # boss 已打完，不再接战，交给 check_exit 结束本次探索
            return
        if self.user_status != UserStatus.ALONE:
            if not self.appear(self.I_TEAM_EMOJI):
                logger.info('Friend disappeared, quit')
                self.quit_exp_main()
                return
        # 先锁阵容, 再处理轮换, 避免轮换先换掉队伍
        if not self._lock_checked:
            self._lock_checked = True
            if self._ensure_team_locked():
                # 点过锁定按钮, 先让画面刷新一帧
                return
        if self.switch_rotate() or self.user_status == UserStatus.MEMBER:
            return
        fire_button = self.get_fire_button()
        if fire_button is not None and self.fire(fire_button):
            return
        # 当前屏幕没有可打的怪，按阶段决定滑动方向
        if self._wq_phase == 'left':
            if self._left_swipes < self._right_swipes and self._left_swipes < self._MAX_SWIPES:
                if self.swipe(self.S_SWIPE_BACKGROUND_LEFT, interval=1.5):
                    self._left_swipes += 1
                    # 连续左滑也会计入点击保护, 到阈值前清一次
                    if self.device.click_record.count(self.S_SWIPE_BACKGROUND_LEFT.name) >= 5:
                        self.device.click_record_clear()
                    return
            logger.info('WQ explore: back to the start, sweep right to the boss')
            self._wq_phase = 'right'
            return
        if self.swipe(self.S_SWIPE_BACKGROUND_RIGHT, interval=1.5):
            if self._wq_phase == 'up':
                self._right_swipes += 1
            if self.arrive_end():
                if self._wq_phase == 'up':
                    # 还没找到高亮怪就到头了，回头扫一遍
                    logger.info('WQ explore: end reached without the highlighted monster, sweep back')
                    self._wq_phase = 'left'
                else:
                    self.quit_exp_main()

    def arrive_end(self) -> bool:
        arrived_end = BaseExploration.arrive_end(self)
        self._explor_cnt += 1 if arrived_end else 0
        return arrived_end

    def fire(self, button) -> bool:
        fired = super().fire(button)
        if fired:
            # 战斗结束后回到地图, 先检查一次悬赏进度
            self._wq_check_after_battle = True
        if fired and self.fire_monster_type == 'wq_normal' and not self._up_fought:
            # 高亮怪已打完，先回扫它左侧没打过的小怪
            self._up_fought = True
            self._wq_phase = 'left'
            logger.info('Highlighted monster defeated, sweep back for the remaining monsters')
        self._explor_cnt += 1 if fired and self.fire_monster_type == 'boss' else 0
        return fired

    def explore(self, goto: RuleImage, num: int):
        logger.info(f'Start exploring with number: {num}')
        self._max_cnt = num
        self._explor_cnt = 0
        self._wq_phase = 'up'
        self._right_swipes = 0
        self._left_swipes = 0
        self._up_fought = False
        self._lock_checked = False
        self._wq_check_after_battle = False
        self.fire_monster_type = ''
        while True:
            self.screenshot()
            if pages.page_exp_entrance == self.get_current_page():
                break
            if self.appear_then_click(goto, interval=2):
                continue
        self.user_status = UserStatus.ALONE
        self.exec_exp_page()

if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    from tasks.WantedQuests.assets import WantedQuestsAssets

    config = Config('oas1')
    device = Device(config)
    t = WQExplore(config, device)
    t.explore(goto=WantedQuestsAssets.I_GOTO_1, num=2)
