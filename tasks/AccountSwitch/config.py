from typing import Any, Dict

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    model_serializer,
    model_validator,
)

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, TimeDelta, MultiLine
from tasks.Component.SwitchAccount.switch_account_config import AccountInfo


class AccountSwitchScheduler(Scheduler):
    # 切完一个号等其它任务跑完, 再切下一个
    success_interval: TimeDelta = Field(
        default=TimeDelta(seconds=30), description='success_interval_help'
    )
    failure_interval: TimeDelta = Field(
        default=TimeDelta(seconds=30), description='failure_interval_help'
    )
    # 优先级最低, 排在其它任务之后
    priority: int = Field(default=15, description='priority_help')


class AccountSwitchConfig(BaseModel):
    usage: MultiLine = Field(
        title='usage',
        default='使用方式:全部立即等待,再立即执行切号任务',
        description='account_switch_usage_help',
    )
    # 字段名避开协战的 account_count, 免得共用同一个翻译 key
    switch_account_count: int = Field(
        default=1,
        ge=1,
        description='switch_account_count_help',
    )
    trigger_all_enabled_tasks: bool = Field(
        default=True,
        description='切号后立即触发当前配置里所有已启用的任务',
    )
    # 脚本自动维护, 不用手改
    current_index: int = Field(
        default=0,
        ge=0,
        description='当前切号指针，脚本自动维护',
    )


class AccountSwitch(ConfigBase):
    scheduler: AccountSwitchScheduler = Field(default_factory=AccountSwitchScheduler)
    account_switch_config: AccountSwitchConfig = Field(
        default_factory=AccountSwitchConfig
    )
    account_list: list[AccountInfo] = None

    @model_validator(mode='before')
    @classmethod
    def validator_account_list(cls, value: dict) -> Any:
        # account_list_1/2/... 平铺存储, 这里聚合成列表
        account_count = value.get('account_switch_config', {}).get(
            'switch_account_count', 1
        )
        account_list = value.setdefault('account_list', [])

        remove_keys = []
        for key, item_value in value.items():
            if key == 'account_list' or 'account_list' not in key:
                continue
            try:
                account = AccountInfo(**item_value)
                if account.is_valid():
                    account_list.append(account)
                remove_keys.append(key)
            except (TypeError, ValidationError):
                continue

        for key in remove_keys:
            del value[key]

        # 不足账号数量就补空账号, 否则序列化不出 account_list_N, GUI 不渲染账号卡
        if len(account_list) < account_count:
            account_list.extend(
                AccountInfo() for _ in range(account_count - len(account_list))
            )

        return value

    @model_serializer()
    def serializer_model(self) -> Dict[str, Any]:
        data = {}
        for key, value in self.__dict__.items():
            if isinstance(value, list):
                for index, item in enumerate(value):
                    data[f'{key}_{index + 1}'] = item.model_dump()
            else:
                data[key] = (
                    value.model_dump() if isinstance(value, BaseModel) else value
                )
        return data
