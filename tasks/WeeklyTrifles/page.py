from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.default_pages import page_collection
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.WeeklyTrifles.assets import WeeklyTriflesAssets

page_shikigami_collection = Page(WeeklyTriflesAssets.I_WT_SCROLL)
page_collection.connect(page_shikigami_collection, GameUiAssets.I_CHECK_COLLECTION,
                                  key="page_collection->page_shikigami_collection")
page_shikigami_collection.connect(page_collection, GlobalGameAssets.I_UI_BACK_YELLOW,
                                  key="page_shikigami_collection->page_collection")

page_shikigami_scroll = Page(WeeklyTriflesAssets.I_WT_COLLECT)
page_shikigami_collection.connect(page_shikigami_scroll, WeeklyTriflesAssets.I_WT_SCROLL,
                                  key="page_shikigami_collection->page_shikigami_scroll")
page_shikigami_scroll.connect(page_shikigami_collection, GlobalGameAssets.I_UI_BACK_BLUE,
                              key="page_shikigami_scroll->page_shikigami_collection")
