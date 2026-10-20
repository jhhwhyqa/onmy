# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta, time
from enum import Enum
from module.logger import logger

from pydantic import BaseModel, Field, model_validator, validator

from tasks.AbyssShadows.config import Condition
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time, dynamic_hide
from typing import Optional


CLIMB_TYPES = ('pass', 'ap', 'ap100', 'boss')
LEGACY_GENERAL_KEYS = (
    'limit_time', 'pass_limit', 'ap_limit', 'ap100_limit', 'boss_limit',
    'run_sequence', 'active_souls_clean', 'random_sleep',
)


class RunOrder(str, Enum):
    """爬塔活动的执行目标：预设只跑单项，多项走自定义。"""
    PASS = '仅门票'
    AP = '仅体力'
    AP100 = '仅百体'
    BOSS = '仅首领'
    CUSTOM = '自定义'


RUN_ORDER_SEQUENCE = {
    RunOrder.PASS: ('pass',),
    RunOrder.AP: ('ap',),
    RunOrder.AP100: ('ap100',),
    RunOrder.BOSS: ('boss',),
}
RUN_ORDER_VALUES = {order.value for order in RunOrder}
DEFAULT_RUN_SEQUENCE = 'pass,ap,ap100,boss'
# 旧版「整组顺序」预设，迁移时转成自定义顺序
LEGACY_RUN_ORDERS = {
    '默认顺序': DEFAULT_RUN_SEQUENCE,
    '门票最后': 'ap,ap100,boss,pass',
    '首领优先': 'boss,pass,ap,ap100',
}


class GeneralConfig(ConfigBase):
    limit_time: Time = Field(default=Time(hour=1, minute=30), description='总限制时间')
    pass_limit: int = Field(default=50, description='门票爬塔最多挑战多少场, 0 表示不执行')
    ap_limit: int = Field(default=300, description='体力爬塔最多挑战多少场, 0 表示不执行')
    ap100_limit: int = Field(default=20, description='百体爬塔最多挑战多少场, 0 表示不执行')
    boss_limit: int = Field(default=20, description='首领战最多挑战多少场, 0 表示不执行')
    run_order: RunOrder = Field(
        default=RunOrder.CUSTOM,
        title='执行顺序',
        description='执行目标\n'
                    '仅门票/仅体力/仅百体/仅首领: 只执行选中的这一项\n'
                    '自定义: 按下方「自定义顺序」执行, 可以填写多个',
    )
    run_sequence: str = Field(default=DEFAULT_RUN_SEQUENCE,
                              title='自定义顺序',
                              description='仅在执行顺序选择「自定义」时生效\n'
                                          'pass:门票,ap100:100体,boss:boss战,ap:体力\n'
                                          '逗号分隔,从左到右依次运行\n'
                                          '例:pass,ap100,boss,ap=门票->100体->boss战->体力')
    # # 门票爬塔buff
    # pass_buff: str = Field(default='buff_4,buff_5', description='门票爬塔加成,buff1-5,加成页从左往右顺序,清空则不切换加成')
    # # 体力爬塔buff
    # ap_buff: str = Field(default='buff_4,buff_5', description='体力爬塔加成,buff1-5,加成页从左往右顺序,清空则不切换加成')
    # # boss爬塔buff
    # boss_buff: str = Field(default='buff_1,buff_3', description='boss战爬塔加成,buff1-5,加成页从左往右顺序,清空则不切换加成')
    # 结束后激活 御魂清理
    active_souls_clean: bool = Field(default=False, description='是否运行结束后清理御魂')
    # 点击战斗随机休息
    random_sleep: bool = Field(default=False, description='是否启用在点击战斗前随机休息')

    @property
    def limit_time_v(self) -> timedelta:
        if isinstance(self.limit_time, time):
            return timedelta(hours=self.limit_time.hour, minutes=self.limit_time.minute,
                             seconds=self.limit_time.second)
        return self.limit_time

    @property
    def run_sequence_v(self) -> list[str]:
        """预设只执行单项；自定义按填写的顺序执行多项"""
        if self.run_order in RUN_ORDER_SEQUENCE:
            sequence = list(RUN_ORDER_SEQUENCE[self.run_order])
        else:
            sequence = self.valid_run_sequence()
        return [climb_type for climb_type in sequence if getattr(self, f'{climb_type}_limit', 0) > 0]

    # @model_validator(mode='after')
    def valid_run_sequence(self) -> list[str]:
        """校验自定义顺序并返回解析后的列表"""
        raw_sequence = (self.run_sequence or '').strip()
        if not raw_sequence:
            raise ValueError('run sequence cannot be empty')
        sequence_list = [climb_type.strip() for climb_type in raw_sequence.split(',') if climb_type.strip()]
        if not sequence_list:
            raise ValueError('run sequence cannot be empty')
        for climb_type in sequence_list:
            if climb_type not in CLIMB_TYPES:
                raise ValueError(f'run sequence can only be one of {", ".join(CLIMB_TYPES)}, now is {climb_type}')
        return sequence_list

    @validator('limit_time', pre=True, always=True)
    def parse_limit_time(cls, value):
        if isinstance(value, str):
            if value.isdigit():
                try:
                    value = int(value)
                except ValueError:
                    logger.warning('Invalid limit_time value. Expected format: seconds')
                    return time(hour=0, minute=30, second=0)
                delta = timedelta(seconds=value)
                return time(hour=delta.seconds // 3600, minute=delta.seconds // 60 % 60, second=delta.seconds % 60)
            else:
                try:
                    return time.fromisoformat(value)
                except ValueError:
                    logger.warning('Invalid limit_time value. Expected format: HH:MM:SS')
                    return time(hour=0, minute=30, second=0)
        return value


def check_soul_by_number(enable_switch: bool, group_team: str, label: str):
    if not enable_switch:
        return
    if not group_team or group_team == "-1,-1":
        raise ValueError(f"[{label}]Switch Soul configuration is enabled, but there is no setting")
    if ',' not in group_team:
        raise ValueError(f"[{label}]The switch soul configuration must be in English ','")
    parts = group_team.split(',')
    if len(parts) != 2:
        raise ValueError(f"[{label}]The length of the switch soul configuration must be equal to 2")
    if not all(p.strip().isdigit() for p in parts):
        raise ValueError(f"[{label}]Switching soul configurations must be numeric")


def check_soul_by_ocr(enable_switch: bool, group_team: str, label: str):
    if not enable_switch:
        return
    if not group_team:
        raise ValueError(f"[{label}]Switch Soul configuration is enabled, but there is no setting")
    if ',' not in group_team:
        raise ValueError(f"[{label}]The switch soul configuration must be in English ','")
    parts = group_team.split(',')
    if len(parts) != 2:
        raise ValueError(f"[{label}]The length of the switch soul configuration must be equal to 2")


class SwitchSoulConfig(BaseModel):
    enable_switch_pass: bool = Field(default=False)
    pass_group_team: str = Field(default='-1,-1', description='pass_group_team_help')
    enable_switch_pass_by_name: bool = Field(default=False)
    pass_group_team_name: str = Field(default='')

    enable_switch_ap: bool = Field(default=False)
    ap_group_team: str = Field(default='-1,-1')
    enable_switch_ap_by_name: bool = Field(default=False)
    ap_group_team_name: str = Field(default='')

    enable_switch_boss: bool = Field(default=False)
    boss_group_team: str = Field(default='-1,-1')
    enable_switch_boss_by_name: bool = Field(default=False)
    boss_group_team_name: str = Field(default='')

    enable_switch_ap100: bool = Field(default=False)
    ap100_group_team: str = Field(default='-1,-1')
    enable_switch_ap100_by_name: bool = Field(default=False)
    ap100_group_team_name: str = Field(default='')

    # @model_validator(mode='after')
    def validate_switch_soul(self):
        label_set = self.get_label_set()
        for label in label_set:
            enable_num = getattr(self, f"enable_switch_{label}", False)
            team = getattr(self, f"{label}_group_team", None)
            check_soul_by_number(enable_num, team, label=label.upper())

            enable_ocr = getattr(self, f"enable_switch_{label}_by_name", False)
            team_name = getattr(self, f"{label}_group_team_name", None)
            check_soul_by_ocr(enable_ocr, team_name, label=label.upper())
        return self

    def get_label_set(self):
        return {field.replace("enable_switch_", "") for field in self.model_fields if
                field.startswith("enable_switch_") and not field.endswith("by_name")}


class RichManConfig(ConfigBase):
    buy_ap: bool = Field(default=False, description='是否购买体力')
    buy_reward: bool = Field(default=False, description='是否购买奖励积分')
    buy_ticket: bool = Field(default=False, description='是否购买定向骰子')


class BossBattleConfig(GeneralBattleConfig):
    exit_strategy: str = Field(default='FALSE', title='首领退出策略',
                               description='TRUE/FALSE:秒退/打到底\n'
                                           '数字1-999:x秒后退出\n'
                                           '数字1000+:造成伤害达到y后退出')

    def generate_quit_condition(self) -> Optional[Condition]:
        """按退出策略生成对应的退出判断条件，未启用退出时返回 None。"""
        if not self.exit_strategy or self.exit_strategy.upper() == 'FALSE':
            return None
        return Condition(self.exit_strategy)


class ActivityShikigami(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    general_config: GeneralConfig = Field(default_factory=GeneralConfig)
    rich_man: RichManConfig = Field(default_factory=RichManConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)

    pass_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    ap_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    boss_battle_conf: BossBattleConfig = Field(default_factory=BossBattleConfig)
    ap100_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)

    hide_fields = dynamic_hide('rich_man')

    @property
    def run_sequence_v(self) -> list[str]:
        """按配置顺序返回次数大于 0 的活动"""
        return self.general_config.run_sequence_v

    @model_validator(mode='before')
    @classmethod
    def migrate_legacy_config(cls, data):
        """兼容旧版 general_climb：公共项与各活动次数统一并入 general_config。"""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        old_general = data.pop('general_climb', None)
        if isinstance(old_general, BaseModel):
            old_general = old_general.model_dump()
        general = data.get('general_config')
        if isinstance(general, BaseModel):
            general = general.model_dump()
        general = dict(general) if isinstance(general, dict) else {}
        if isinstance(old_general, dict):
            for key in LEGACY_GENERAL_KEYS:
                if key in old_general and key not in general:
                    general[key] = old_general[key]
        # 兼容次数曾被放进各活动战斗配置的结构
        for climb_type in CLIMB_TYPES:
            conf_key = f'{climb_type}_battle_conf'
            conf = data.get(conf_key)
            if not isinstance(conf, dict) or 'limit' not in conf:
                continue
            conf = dict(conf)
            limit = conf.pop('limit')
            general.setdefault(f'{climb_type}_limit', limit)
            data[conf_key] = conf
        # 旧的整组顺序预设已取消，转成自定义顺序；未知值回落到自定义
        legacy_order = general.get('run_order')
        if isinstance(legacy_order, RunOrder):
            legacy_order = legacy_order.value
        if isinstance(legacy_order, str):
            legacy_order = legacy_order.strip()
        if legacy_order is not None:
            if legacy_order in LEGACY_RUN_ORDERS:
                general['run_order'] = RunOrder.CUSTOM.value
                general['run_sequence'] = LEGACY_RUN_ORDERS[legacy_order]
            elif legacy_order not in RUN_ORDER_VALUES:
                general['run_order'] = RunOrder.CUSTOM.value
        if old_general is not None or 'general_config' in data:
            data['general_config'] = general
        return data
