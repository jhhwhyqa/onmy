from tasks.FloatParade.assets import FloatParadeAssets
from tasks.GameUi.default_pages import page_main
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets

# 花车主界面
page_fp_main = Page(FloatParadeAssets.I_FP_TASKS)
page_fp_main.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key='page_fp_main->page_main')
page_main.connect(page_fp_main, FloatParadeAssets.I_FP_ACCESS, key='page_main->page_fp_main')
# 花车任务界面
page_fp_task = Page(FloatParadeAssets.I_FP_UPGRADE)
page_fp_task.connect(page_fp_main, GlobalGameAssets.I_UI_BACK_YELLOW, key='page_fp_task->page_fp_main')
page_fp_main.connect(page_fp_task, FloatParadeAssets.I_FP_TASKS, key='page_fp_main->page_fp_task')
# 花车放置界面
page_fp_placement = Page(FloatParadeAssets.I_FP_PR_CHECK)
page_fp_placement.connect(page_fp_main, GlobalGameAssets.I_UI_BACK_RED, key='page_fp_placement->page_fp_main')
page_fp_main.connect(page_fp_placement, FloatParadeAssets.I_FP_PLACEMENT_REWARD_ENTER, key='page_fp_main->page_fp_placement')
