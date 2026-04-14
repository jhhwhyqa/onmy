from tasks.AbyssShadows.assets import AbyssShadowsAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.page import Page, page_guild

page_guild_shenshe = Page(AbyssShadowsAssets.I_CHECK_SHENSHE)
page_guild.connect(page_guild_shenshe, AbyssShadowsAssets.I_RYOU_SHENSHE, key="page_guild->page_guild_shenshe")
page_guild_shenshe.connect(page_guild, GameUiAssets.I_BACK_Y, key="page_guild_shenshe->page_guild")

page_abyss = Page(AbyssShadowsAssets.I_CHECK_ABYSS)
page_guild_shenshe.connect(page_abyss, AbyssShadowsAssets.L_SHENSHE_TO_ABYSS, key="page_guild_shenshe->page_abyss")
page_abyss.connect(page_guild_shenshe, GameUiAssets.I_BACK_BLUE, key="page_abyss->page_guild_shenshe")
