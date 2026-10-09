from tasks.GameUi.page import Page, page_secret_zones
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.EasySecret.assets import EasySecretAssets

# 秘闻详情页（层数列表 + 「挑战」按钮）
page_easy_secret_detail = Page(EasySecretAssets.I_ES_FIRE)
page_easy_secret_detail.connect(
    page_secret_zones,
    GlobalGameAssets.I_UI_BACK_RED,
    key='page_easy_secret_detail->page_secret_zones',
)
