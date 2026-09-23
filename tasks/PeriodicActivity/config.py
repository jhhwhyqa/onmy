# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum

from pydantic import BaseModel, Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


class PeriodicActivityName(str, Enum):
    """
    周期活动里可选的子活动
    """
    DYE_TRIALS = 'dye_trials'  # 灵染试炼
    QUIZ = 'quiz'  # 智力竞赛
    GUGU_ART_STUDIO = 'gugu_art_studio'  # 呱呱画室


class PeriodicActivityConfig(BaseModel):
    # 本次调度执行哪一个周期活动
    activity: PeriodicActivityName = Field(default=PeriodicActivityName.DYE_TRIALS,
                                           description='periodic_activity_name_help')


class QuizConfig(BaseModel):
    # 打多少轮
    quiz_cnt: int = Field(default=1, description='quiz_cnt_help')
    # 每轮多少道题
    quiz_per_round: int = Field(default=150, description='quiz_per_round_help')


class PeriodicActivity(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    periodic_activity_config: PeriodicActivityConfig = Field(default_factory=PeriodicActivityConfig)
    # 灵染试炼、呱呱画室共用（两者都需要在式神录切换御魂）
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    # 呱呱画室战斗配置
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    # 智力竞赛配置
    quiz_config: QuizConfig = Field(default_factory=QuizConfig)
