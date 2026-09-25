# This Python file uses the following encoding: utf-8
from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase, dynamic_hide
from tasks.Component.config_scheduler import Scheduler


class LBSConfig(ConfigBase):
    buy_blessing_enable: bool = Field(default=False, description='buy_blessing_enable_help')


class LBSBattleConfig(GeneralBattleConfig):
    """协战队伍页面没有锁定阵容控件。"""

    lbs_hide_fields = dynamic_hide('lock_team_enable')


class LBS(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    lbs_config: LBSConfig = Field(default_factory=LBSConfig)
    general_battle_config: LBSBattleConfig = Field(default_factory=LBSBattleConfig)
    switch_soul: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
