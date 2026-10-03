# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

from enum import Enum
from pydantic import BaseModel, Field

from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler


class Strategy(str, Enum):
    Majority = 'frog_majority'
    Minority = 'frog_minority'
    Bilibili = 'frog_bilibili'
    Dashen = 'frog_dashen'
    Oas = 'frog_oas'
    AlwaysRed = 'frog_always_red'
    AlwaysBlue = 'frog_always_blue'

class FrogBossConfig(ConfigBase):
    before_end_frog: Time = Field(default=Time(0, 15, 0), description='before_end_frog_help')
    strategy_frog: Strategy = Field(default=Strategy.Majority, description='strategy_frog_help')
    # 以下两项仅 Oas(frog_oas) 策略使用：
    # 大众票权重，0 = 不把大众票计入；可信度统计窗口，0 = 用全部历史，N = 只看最近 N 局结算
    oas_crowd_weight: float = Field(default=0.0, description='oas_crowd_weight_help')
    oas_reliability_window: int = Field(default=0, description='oas_reliability_window_help')

class FrogBoss(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    frog_boss_config: FrogBossConfig = Field(default_factory=FrogBossConfig)



