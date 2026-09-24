# This Python file uses the following encoding: utf-8
"""月华流光的页面定义与庭院入口查找。

页面结构：庭院 -> 月华流光大厅 -> 挑战页，两级都能退回庭院。
入口在庭院右侧的活动栏目里，需要逐轮切换栏目才能找到，所以大厅页挂了
`I_TOGGLE_BUTTON` 作为进入失败的处置动作，另外也提供了显式查找函数
`find_moonlight_entry`（流程里先用它定位，避免依赖导航器的重试次数）。
"""
import time

from module.logger import logger

from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.action import conditional_action
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.page import Page, page_main
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.VersionActivity.assets import VersionActivityAssets

# 月华流光大厅
page_moon_lobby = Page(VersionActivityAssets.I_MOON_LOBBY, priority=75)
# 月华流光挑战页
page_moon_battle = Page(VersionActivityAssets.I_MOON_BATTLE, priority=75)

page_moon_lobby.add_enter_failure_hooks(
    # 庭院右侧活动栏目切换（入口不一定在第一栏）
    RightActivityAssets.I_TOGGLE_BUTTON,
    # 活动奖励弹窗
    conditional_action(GlobalGameAssets.I_UI_REWARD, random_click),
    # 遮挡的关闭按钮 / 剧情页
    GlobalGameAssets.I_UI_BACK_RED,
)
page_main.connect(
    page_moon_lobby, VersionActivityAssets.I_MOON_ENTRY, key="page_main->page_moon_lobby"
)
page_moon_lobby.connect(
    page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_moon_lobby->page_main"
)
page_moon_lobby.connect(
    page_moon_battle,
    VersionActivityAssets.I_MOON_ENTER_BATTLE,
    key="page_moon_lobby->page_moon_battle",
)
page_moon_battle.connect(
    page_moon_lobby, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_moon_battle->page_moon_lobby"
)


def find_moonlight_entry(task) -> bool:
    """在庭院右侧活动栏目里查找月华流光入口，最多切换八轮。

    :param task: 任意带 `screenshot` / `appear` / `appear_then_click` 的任务实例
    :return: 找到入口返回 True；不在庭院或找不到返回 False
    """
    switched = 0
    for _ in range(8):
        task.screenshot()
        if not task.appear(task.I_CHECK_MAIN):
            logger.warning("Moonlight entry search: not on main page")
            return False
        if task.appear(VersionActivityAssets.I_MOON_ENTRY):
            return True
        if task.appear(RightActivityAssets.I_TOGGLE_BUTTON):
            time.sleep(1.0)
            task.screenshot()
            if task.appear_then_click(RightActivityAssets.I_TOGGLE_BUTTON, interval=1):
                switched += 1
        time.sleep(0.5)
    task.screenshot()
    if task.appear(VersionActivityAssets.I_MOON_ENTRY):
        return True
    logger.warning("Moonlight entry not found after %s column switches", switched)
    return False
