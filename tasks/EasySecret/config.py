# This Python file uses the following encoding: utf-8
from pydantic import BaseModel, Field

from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig


class EasySecretConfig(BaseModel):
    # 最多挑战到第几层（不挑战下一层）
    max_layer: int = Field(default=5, description='max_layer_help')
    # 需要跳过的高难度秘闻标题，逗号或换行分隔
    # 默认跳过「呱士无双」：它有手动教程，不适合速刷
    skip_secrets: str = Field(default='呱士无双', description='skip_secrets_help')
    # 单次运行最多挑战多少次，0 表示不限制
    battle_limit: int = Field(default=0, description='battle_limit_help')


class EasySecret(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    easy_secret_config: EasySecretConfig = Field(default_factory=EasySecretConfig)
    general_battle_config: GeneralBattleConfig = Field(
        default_factory=GeneralBattleConfig
    )
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
