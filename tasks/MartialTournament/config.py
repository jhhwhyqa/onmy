# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta, time

from pydantic import BaseModel, Field, validator

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time


class MartialTournamentConfig(ConfigBase):
    """Martial Tournament activity config"""
    limit_time: Time = Field(default=Time(hour=1, minute=30), description='limit_time_help')
    run_sequence: str = Field(default='pass,ap',
                              description='mt_run_sequence_help')
    pass_limit: int = Field(default=50, description='mt_pass_limit_help')
    ap_limit: int = Field(default=300, description='ap_limit')
    # 开启使用注灵搜寻券
    use_pass_2: bool = Field(default=False, description='mt_use_pass_2_help')
    # 结束后激活御魂清理
    active_souls_clean: bool = Field(default=False, description='active_souls_clean_help')
    # 点击战斗随机休息
    random_sleep: bool = Field(default=False, description='random_sleep_help')

    @property
    def limit_time_v(self) -> timedelta:
        if isinstance(self.limit_time, time):
            return timedelta(hours=self.limit_time.hour, minutes=self.limit_time.minute,
                             seconds=self.limit_time.second)
        return self.limit_time

    @property
    def sequence_list(self) -> list:
        """根据运行顺序返回启用的爬塔类型列表"""
        str_list = [climb_type.strip() for climb_type in self.run_sequence.split(',')]
        return [climb_type for climb_type in str_list if getattr(self, f'{climb_type}_limit', 0) > 0]

    @validator('limit_time', pre=True, always=True)
    def parse_limit_time(cls, value):
        if isinstance(value, str):
            if value.isdigit():
                try:
                    value = int(value)
                except ValueError:
                    return time(hour=0, minute=30, second=0)
                delta = timedelta(seconds=value)
                return time(hour=delta.seconds // 3600, minute=delta.seconds // 60 % 60, second=delta.seconds % 60)
            else:
                try:
                    return time.fromisoformat(value)
                except ValueError:
                    return time(hour=0, minute=30, second=0)
        return value


class SwitchSoulConfig(BaseModel):
    # 群体boss御魂配置
    enable_switch_group: bool = Field(default=False)
    group_boss_team: str = Field(default='-1,-1', description='group_boss_team_help')
    enable_switch_group_by_name: bool = Field(default=False)
    group_boss_team_name: str = Field(default='')
    # 单体boss御魂配置
    enable_switch_single: bool = Field(default=False)
    single_group_team: str = Field(default='-1,-1', description='single_group_team_help')
    enable_switch_single_by_name: bool = Field(default=False)
    single_group_team_name: str = Field(default='')
    # 体力爬塔御魂配置
    enable_switch_mt_ap: bool = Field(default=False)
    mt_ap_team: str = Field(default='-1,-1', description='mt_ap_team_help')
    enable_switch_mt_ap_by_name: bool = Field(default=False)
    mt_ap_team_name: str = Field(default='')


class MartialTournament(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    general_climb: MartialTournamentConfig = Field(default_factory=MartialTournamentConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    # 群体boss战斗配置
    group_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    # 单体boss战斗配置
    single_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    # 体力爬塔战斗配置
    mt_ap_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
