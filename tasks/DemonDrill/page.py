# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.default_pages import page_main
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page import page_shikigami_records
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.DemonDrill.assets import DemonDrillAssets

# 逢魔演武界面
page_demon_drill = Page(DemonDrillAssets.I_DRILL_CHECK)
page_demon_drill.add_enter_failure_hooks(RightActivityAssets.I_TOGGLE_BUTTON)
page_demon_drill.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_demon_drill->page_main")
page_main.connect(page_demon_drill, DemonDrillAssets.I_DRILL_ENTRY, key="page_main->page_demon_drill")

# 演武挑战页面
page_drill_challenge = Page(any_of(DemonDrillAssets.I_DRILL_CHALLENGE_CHECK, DemonDrillAssets.I_DRILL_FIRE))
page_drill_challenge.connect(page_demon_drill, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_drill_challenge->page_demon_drill")
page_demon_drill.connect(page_drill_challenge, DemonDrillAssets.I_DRILL_CHALLENGE, key="page_demon_drill->page_drill_challenge")

# 式神录 <-> 演武挑战页面
page_drill_challenge.connect(page_shikigami_records, DemonDrillAssets.I_DRILL_GOTO_SHIKIGAMI, key="page_drill_challenge->page_shikigami_records")
page_shikigami_records.connect(page_drill_challenge, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_shikigami_records->page_drill_challenge", cost=2)
