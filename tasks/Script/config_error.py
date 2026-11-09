# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import BaseModel, Field, model_validator

from module.logger import logger


class Error(BaseModel):
    handle_error: bool = Field(default=True,
                               description='handle_error_help')
    error_repeated: bool = Field(default=False,
                               description='是否多次出错关闭模拟器')
    save_error: bool = Field(default=True,
                             description='')
    screenshot_length: int = Field(
        default=1,
        description='',
        ge=1,
    )
    notify_enable: bool = Field(default=False,
                                description='')

    @model_validator(mode='before')
    @classmethod
    def drop_legacy_notify_config(cls, value):
        """渠道内容已统一到 config/notify_channel.yaml，忽略旧配置里残留的 notify_config。"""
        if isinstance(value, dict):
            value.pop('notify_config', None)
        return value


