# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta
from enum import Enum
from pydantic import BaseModel, Field

from tasks.Component.config_scheduler import Scheduler as BaseScheduler
from tasks.Component.config_base import ConfigBase, TimeDelta


class LevelReward(str, Enum):
    ONE = '蛇皮/青吉鬼'
    TWO = '金币/勾玉'
    THREE = '体力/樱饼'

class FloatParadeConfig(BaseModel):
    # level_reward1: LevelReward = Field(default=LevelReward.THREE)
    # level_reward2: LevelReward = Field(default=LevelReward.ONE)
    collect_placement_reward: bool = Field(default=True)
    collect_exp: bool = Field(default=True)

class FloatParade(ConfigBase):
    scheduler: BaseScheduler = Field(default_factory=BaseScheduler)
    float_parade: FloatParadeConfig = Field(default_factory=FloatParadeConfig)