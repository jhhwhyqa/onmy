# This Python file uses the following encoding: utf-8
from enum import Enum

from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase, dynamic_hide
from tasks.Component.config_scheduler import Scheduler


class LBSMode(str, Enum):
    """现世妖约的组队方式。"""
    # 创建公开房间，等待随机路人加入后开战
    PUBLIC_TEAM = 'public_team'
    # 创建不公开(仅邀请)房间，不等队友，进房后直接挑战单刷
    SOLO = 'solo'


class LBSConfig(ConfigBase):
    run_mode: LBSMode = Field(default=LBSMode.PUBLIC_TEAM, description='run_mode_help')
    buy_blessing_enable: bool = Field(default=False, description='buy_blessing_enable_help')


class LBSBattleConfig(GeneralBattleConfig):
    """协战队伍页面没有锁定阵容控件。"""

    lbs_hide_fields = dynamic_hide('lock_team_enable')


class LBS(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    lbs_config: LBSConfig = Field(default_factory=LBSConfig)
    general_battle_config: LBSBattleConfig = Field(default_factory=LBSBattleConfig)
    switch_soul: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
