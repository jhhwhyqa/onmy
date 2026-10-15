# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import Field, BaseModel

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


class DemonDrillConfig(BaseModel):
    # 是否执行逢魔委派
    demon_drill_delegation_enable: bool = Field(default=False, description='demon_drill_delegation_enable_help')


class DemonDrill(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    demon_drill_config: DemonDrillConfig = Field(default_factory=DemonDrillConfig)
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
