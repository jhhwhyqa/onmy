from pydantic import BaseModel, Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase


class ActivityExplorationConfig(BaseModel):
    encounter_battle_enable: bool = Field(default=False)


class ActivityExploration(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    activity_exploration_config: ActivityExplorationConfig = Field(
        default_factory=ActivityExplorationConfig
    )
    general_battle_config: GeneralBattleConfig = Field(
        default_factory=GeneralBattleConfig
    )
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
