from pydantic import BaseModel, Field
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase


class LevelRushConfig(BaseModel):
    random_name_enable: bool = Field(default=False)
    level_7_mark: bool = Field(default=False)
    assist_up_mark: bool = Field(default=False)


class LevelRush(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    level_rush_config: LevelRushConfig = Field(default_factory=LevelRushConfig)
