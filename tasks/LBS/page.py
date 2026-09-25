from tasks.GameUi.default_pages import page_main, page_shikigami_records
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.LBS.assets import LBSAssets
from tasks.Component.RightActivity.assets import RightActivityAssets

# 线下庆典活动首页；入口位于庭院右下角。
page_lbs = Page(any_of(LBSAssets.I_CHECK_LBS, LBSAssets.I_LBS_TEAM))
page_lbs.add_enter_failure_hooks(RightActivityAssets.I_TOGGLE_BUTTON)
page_main.connect(page_lbs, LBSAssets.I_MAIN_GOTO_LBS, key='page_main->page_lbs')

# 现世商店。购买祝福后通过左侧“活动”页签返回活动首页。
page_lbs_shop = Page(any_of(LBSAssets.I_CHECK_LBS_SHOP, LBSAssets.I_LBS_BLESSING))
page_lbs.connect(
    page_lbs_shop, LBSAssets.I_ACTIVITY_GOTO_SHOP, key='page_lbs->page_lbs_shop'
)
page_lbs_shop.connect(
    page_lbs, LBSAssets.I_SHOP_GOTO_ACTIVITY, key='page_lbs_shop->page_lbs'
)

# 战斗结算会短暂显示现世地图；从右下角的活动图标返回活动首页。
page_lbs_map = Page(LBSAssets.I_CHECK_LBS_MAP)
page_lbs_map.connect(
    page_lbs, LBSAssets.I_MAP_GOTO_ACTIVITY, key='page_lbs_map->page_lbs'
)
page_lbs_map.connect(
    page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key='page_lbs_map->page_main'
)
