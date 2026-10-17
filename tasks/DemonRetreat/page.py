from tasks.DemonRetreat.assets import DemonRetreatAssets
from tasks.GameUi.action import sequence
from tasks.GameUi.default_pages import page_guild, page_shirin
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets

# 开启界面
page_demon_retreat_open = Page(DemonRetreatAssets.I_HUNT_CHECK, priority=20)
page_demon_retreat_open.connect(page_shirin, GlobalGameAssets.I_UI_BACK_CIRCLE,
                                key="page_demon_retreat_open->page_shirin")

# 挑战界面
page_demon_retreat_challenge = Page(DemonRetreatAssets.I_CHALLENGE_CHECK, priority=30)
page_demon_retreat_challenge.connect(
    page_guild,
    sequence(GlobalGameAssets.I_UI_BACK_CIRCLE, GlobalGameAssets.I_UI_CONFIRM_SAMLL, success_index=1),
    key="page_demon_retreat_challenge->page_guild")

page_demon_retreat_open.connect(page_demon_retreat_challenge, DemonRetreatAssets.I_ENTER_FIRE,
                                key="page_demon_retreat_open->page_demon_retreat_challenge")
