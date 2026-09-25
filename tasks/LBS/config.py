# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import BaseModel, Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler


class LBSConfig(BaseModel):
    # 限制次数
    limit_count: int = Field(
        default=35, ge=1, title='限制次数', description='挑战成功次数的上限'
    )
    # 限制时间
    limit_time: Time = Field(
        default=Time(minute=30), title='最长运行时间', description='格式 时:分:秒，例如00:30:00'
    )
    # 购买现世祝福（现世商店，每日限购一次，100 勾玉）
    buy_blessing_enable: bool = Field(
        default=False, title='购买现世祝福', description='每日一次，100 勾玉'
    )


class LBS(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    lbs_config: LBSConfig = Field(default_factory=LBSConfig)
    # 执行任务前在式神录切换御魂（组号队伍号 / 按名称两种方式）
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    # 出战预设：勾选 preset_enable 后按预设组 / 预设队出战（不勾选则用当前阵容）
    battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
