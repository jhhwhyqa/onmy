from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.default_pages import page_main, page_shikigami_records
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.PeriodicActivity.assets import PeriodicActivityAssets

# 呱呱画室主页面
page_gugu = Page(any_of(PeriodicActivityAssets.I_CHECK_GUGU_ACT, PeriodicActivityAssets.I_SUBMIT_PAINT,
                        PeriodicActivityAssets.I_OBTAIN_PAINT))
page_gugu.add_enter_failure_hooks(RightActivityAssets.I_TOGGLE_BUTTON)
page_gugu.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_gugu->page_main")
page_main.connect(page_gugu, PeriodicActivityAssets.I_GAS_MAIN_TO_GUGU, key="page_main->page_gugu")

# 呱呱画室挑战页面
page_gugu_fire = Page(any_of(PeriodicActivityAssets.I_GAS_CAN_FIRE, PeriodicActivityAssets.I_GAS_CANNOT_FIRE))
page_gugu_fire.connect(page_gugu, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_gugu_fire->page_gugu")
page_gugu.connect(page_gugu_fire, PeriodicActivityAssets.I_OBTAIN_PAINT, key="page_gugu->page_gugu_fire")
