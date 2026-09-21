from pydantic import BaseModel, Field
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase


class LevelRushConfig(BaseModel):
    exploration_chapter_max_15_enable: bool = Field(
        default=True,
        description='不开就得手动配阵容，不然打不过',
    )
    skip_to_30_stop_enable: bool = Field(default=True)
    level_7_mark: bool = Field(default=False)
    assist_up_mark: bool = Field(default=False)
    get_achievement_reward_mark: bool = Field(
        default=False,
        description='获取成就中的勾玉购买体力',
    )
    skip_to_30_mark: bool = Field(default=False)


class LevelRush(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    level_rush_config: LevelRushConfig = Field(default_factory=LevelRushConfig)
