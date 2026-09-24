# This Python file uses the following encoding: utf-8
"""限时活动：版本活动（月华流光）的配置。"""
from datetime import time, timedelta

from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler


class VersionActivityConfig(ConfigBase):
    challenge_limit: int = Field(default=1, ge=0, title='挑战次数')
    limit_time: Time = Field(default=Time(hour=1, minute=30), title='最长运行时间')
    random_sleep: bool = Field(default=False, title='随机休息')
    active_souls_clean: bool = Field(default=False, title='结束后激活御魂清理')

    @property
    def limit_time_v(self) -> timedelta:
        """把 limit_time 统一成 timedelta，供流程代码使用。"""
        value = self.limit_time
        if isinstance(value, time):
            return timedelta(
                hours=value.hour, minutes=value.minute, seconds=value.second
            )
        return value


class VersionActivity(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    version_activity_config: VersionActivityConfig = Field(
        default_factory=VersionActivityConfig
    )
    # 执行任务前在式神录切换御魂（组号队伍号 / 按名称两种方式）
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
