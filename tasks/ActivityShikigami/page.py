from tasks.ActivityShikigami.assets import ActivityShikigamiAssets as asa
from tasks.Component.RightActivity.assets import RightActivityAssets as RAA
from tasks.GameUi.assets import GameUiAssets as G
from tasks.GameUi.page import Page, page_main, sequence
from tasks.GlobalGame.assets import GlobalGameAssets as gga

# 爬塔活动主要界面
page_climb_act = Page(asa.I_TO_BATTLE_MAIN)
page_climb_act.add_enter_success_hooks(gga.I_UI_REWARD, asa.I_SKIP_BUTTON, asa.I_CONFIRM_SKIP, asa.I_RED_EXIT)
page_climb_act.connect(page_main, G.I_BACK_Y, key="page_climb_act->page_main")
page_main.connect(page_climb_act, sequence(asa.I_SHI, RAA.I_TOGGLE_BUTTON), key="page_main->page_climb_act")
