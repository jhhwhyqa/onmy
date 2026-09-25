"""LBS 活动相关页面：活动首页 / 现世商店 / 现世地图。

页面定义与素材取自 Hurry2/OnmyojiAutoScript 的 LBS 实现（提交 `62f4c446`
`add(LBS):添加lbs现世活动`），用于两件事：

1. 进「现世商店」买现世祝福（`page_lbs_shop`）
2. 战斗结算会短暂经过「现世地图」页（`page_lbs_map`），注册进页面图后
   导航器能从那里回活动首页，`run_general_battle` 也能把它当作「已离开战斗」
"""
from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.default_pages import page_main
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.LBS.assets import LBSAssets

# 活动首页（庭院右下角进入；也可从现世地图 / 商店返回）
page_lbs = Page(any_of(LBSAssets.I_CHECK_LBS, LBSAssets.I_TEAM_UP))
page_lbs.add_enter_failure_hooks(RightActivityAssets.I_TOGGLE_BUTTON)
page_lbs.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_lbs->page_main")
page_main.connect(page_lbs, LBSAssets.I_MAIN_GOTO_LBS, key="page_main->page_lbs")

# 现世商店（买现世祝福）
page_lbs_shop = Page(any_of(LBSAssets.I_CHECK_LBS_SHOP, LBSAssets.I_LBS_BLESSING))
page_lbs.connect(
    page_lbs_shop, LBSAssets.I_ACTIVITY_GOTO_SHOP, key="page_lbs->page_lbs_shop"
)
page_lbs_shop.connect(
    page_lbs, LBSAssets.I_SHOP_GOTO_ACTIVITY, key="page_lbs_shop->page_lbs"
)

# 现世地图（战斗结算会短暂经过）
page_lbs_map = Page(LBSAssets.I_CHECK_LBS_MAP)
page_lbs_map.connect(
    page_lbs, LBSAssets.I_MAP_GOTO_ACTIVITY, key="page_lbs_map->page_lbs"
)
page_lbs_map.connect(
    page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_lbs_map->page_main"
)
