# This Python file uses the following encoding: utf-8
# @brief    Configurations for Ryou Dokan Toppa (阴阳竂道馆突破配置)
# @author   jackyhwei
# @note     draft version without full test
# github    https://github.com/roarhill/oas
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase, Time, dynamic_hide
from tasks.Component.config_scheduler import Scheduler


class AttackAccountConfig(BaseModel):
    # 当天可攻击次数,用以记录当天运行历史,用作状态恢复,不用配置
    remain_attack_count: int = Field(default=-1, description='remain_attack_count_help')
    # remain_attack_count 值记录的时间,不用配置
    attack_date: str = Field(default='', description='attack_date_help')

    hide_fields = dynamic_hide('remain_attack_count', 'attack_date')

    def init_attack_count(self, callback=None):
        self.attack_date = ''
        self.remain_attack_count = -1
        if not callback:
            return
        callback()

    def set_attack_count(self, count=-1, callback=None):
        if count < 0:
            return
        self.attack_date = datetime.now().strftime("%Y-%m-%d")
        self.remain_attack_count = count
        if not callback:
            return
        callback()

    def del_attack_count(self, count, callback=None):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.attack_date:
            self.attack_date = today
            self.remain_attack_count = -1
        else:
            self.remain_attack_count = max(0, self.remain_attack_count - count)
        if not callback:
            return
        callback()


class DokanConfig(BaseModel):
    dokan_run_time: Time = Field(Time(hour=20, minute=0, second=0), description='dokan_run_time_help')
    # 攻击优先顺序: 见习=0,初级=1...
    dokan_attack_priority: int = Field(default=0, description='dokan_attack_priority_help')
    # 只在周一到周四开启道馆
    monday_to_thursday: bool = Field(default=True, description='monday_to_thursday_help')
    # 道馆最小人数限制
    min_people_num: int = Field(default=-1, description='min_people_num_help')
    # 超过此刷新次数后将最低防守人数减半，最多刷新20次
    find_dokan_refresh_count: int = Field(default=7, description='find_dokan_refresh_count_help')


class DokanBattleConfig(GeneralBattleConfig):
    continuous_battle: bool = True

    @field_validator('continuous_battle', mode='after')
    @classmethod
    def validate_continuous_battle(cls, v):
        return True


class TaskNotifyConfig(BaseModel):
    """任务级通知开关；推送渠道统一读取 config/notify_channel.yaml（见 task_notify.py）。"""

    # 任务结束时推送本次运行的道馆结算截图；关闭时截图只保存在本地
    push_reward_screenshot: bool = Field(default=False, description='push_reward_screenshot_help')
    # 达到最大刷新次数仍未找到道馆时推送提醒
    push_refresh_limit: bool = Field(default=False, description='push_refresh_limit_help')


class ZombieGuild(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    dokan_config: DokanConfig = Field(default_factory=DokanConfig)
    notification_config: TaskNotifyConfig = Field(default_factory=TaskNotifyConfig)
    dokan_member_battle_conf: DokanBattleConfig = Field(default_factory=DokanBattleConfig)
    dokan_member_switch_soul: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    attack_count_config: AttackAccountConfig = Field(default_factory=AttackAccountConfig)

    hide_fields = dynamic_hide('attack_count_config')

    @model_validator(mode='before')
    @classmethod
    def migrate_legacy_notify(cls, value):
        """旧配置的推送开关（dokan_config.push_reward_images + notification_config.enable）
        拆成两个独立开关时，保持原有用户的推送行为。"""
        if not isinstance(value, dict):
            return value
        notify = value.get('notification_config')
        if not isinstance(notify, dict) or 'enable' not in notify:
            return value
        legacy_enable = bool(notify.pop('enable'))
        dokan = value.get('dokan_config')
        legacy_screenshot = legacy_enable
        if isinstance(dokan, dict):
            legacy_screenshot = bool(dokan.pop('push_reward_images', True)) and legacy_enable
        notify.setdefault('push_reward_screenshot', legacy_screenshot)
        notify.setdefault('push_refresh_limit', legacy_enable)
        return value
