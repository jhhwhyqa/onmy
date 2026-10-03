# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta
from pydantic import BaseModel, Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time


class DemonRetreatTime(ConfigBase):
    # 自定义运行时间
    custom_run_time: Time = Field(default=Time(hour=10, minute=0, second=0), description='demon_retreat_time_help')


class DemonRetreatProcess(ConfigBase):
    """首领退治里与狭间相关的开关。

    注意：任务模型顶层的字段必须都是「分组」（嵌套模型），标量字段会让
    ConfigModel.script_task() 生成 GUI 参数时 KeyError('$ref')，整个设置页 500。
    """

    # 首领退治界面右下角若出现「开启狭间」按钮，就点开它（点完继续本次退治）
    # 字段名与 AbyssShadows 的同名开关一致，GUI 里显示「是否自己开启狭间」
    try_start_abyss_shadows: bool = Field(default=False)


class DemonRetreat(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    demon_retreat_time: DemonRetreatTime = Field(default_factory=DemonRetreatTime)
    general_battle: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    process_manage: DemonRetreatProcess = Field(default_factory=DemonRetreatProcess)
