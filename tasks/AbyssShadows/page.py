from tasks.AbyssShadows.assets import AbyssShadowsAssets
from tasks.GameUi.page import Page, page_shirin
from tasks.GlobalGame.assets import GlobalGameAssets

page_abyss = Page(AbyssShadowsAssets.I_CHECK_ABYSS)
page_shirin.connect(page_abyss, AbyssShadowsAssets.L_SHENSHE_TO_ABYSS, key="page_shirin->page_abyss")
page_abyss.connect(page_shirin, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_abyss->page_shirin")
