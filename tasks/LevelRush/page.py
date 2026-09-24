from tasks.GameUi.default_pages import page_main, page_daily
from tasks.GameUi.page_definition import Page
from tasks.LevelRush.assets import LevelRushAssets

# 新手活动页面
page_rookie_act = Page(LevelRushAssets.I_CHECK_ROOKIE_ACT)
page_rookie_act.add_enter_failure_hooks(LevelRushAssets.I_RED_CLOSE)
page_main.connect(
    page_rookie_act,
    LevelRushAssets.I_GOTO_ROOKIE_ACT,
    key="page_main->page_rookie_act",
)
page_rookie_act.connect(
    page_main,
    LevelRushAssets.I_YELLOW_BACK_BUTTON,
    key="page_rookie_act->page_main",
)

# 成就页面
page_achievement = Page(LevelRushAssets.I_CHECK_ACHIEVEMENT)
page_daily.connect(
    page_achievement,
    LevelRushAssets.I_DAILY_GOTO_ACHIEVEMENT,
    key="page_daily->page_achievement",
)
page_achievement.connect(
    page_daily,
    LevelRushAssets.I_YELLOW_BACK_BUTTON,
    key="page_achievement->page_daily",
)
