# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.default_pages import page_main
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.FrogChallenge.assets import FrogChallengeAssets

# 青蛙瓷器挑战赛页面（点击庭院右侧图标直接进入，没有中间页面）
page_frog_challenge = Page(any_of(FrogChallengeAssets.I_CHECK_FROG_CHALLENGE, FrogChallengeAssets.I_FC_FIRE))
page_frog_challenge.add_enter_failure_hooks(RightActivityAssets.I_TOGGLE_BUTTON)
page_frog_challenge.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW,
                            key="page_frog_challenge->page_main")
page_main.connect(page_frog_challenge, FrogChallengeAssets.I_GOTO_FROG_CHALLENGE,
                  key="page_main->page_frog_challenge")
