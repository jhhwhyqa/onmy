from tasks.ActivityExploration.assets import ActivityExplorationAssets
from tasks.GameUi.page import Page, page_main
from tasks.ActivityShikigami.page import page_act

# 爬塔活动剧情界面
page_act_exploration = Page(ActivityExplorationAssets.I_CHECK_ACT_EXPLORATION)
page_act_exploration.add_enter_failure_hooks(
    ActivityExplorationAssets.I_ACT_SKIP, ActivityExplorationAssets.I_ACT_CONFIRM_SKIP
)
page_act.connect(
    page_act_exploration,
    ActivityExplorationAssets.I_ACT_GOTO_ACT_EXPLORATION,
    key="page_act->page_act_exploration",
)
page_act_exploration.connect(
    page_main,
    ActivityExplorationAssets.I_BACK_TO_MAIN,
    key="page_act_exploration->page_main",
)
