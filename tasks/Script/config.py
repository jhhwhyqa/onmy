# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import BaseModel, Field

from tasks.Script.config_device import Device
from tasks.Script.config_error import Error
from tasks.Script.config_optimization import Optimization


class Script(BaseModel):
    device: Device = Field(default_factory=Device)
    error: Error = Field(default_factory=Error)
    optimization: Optimization = Field(default_factory=Optimization)

    def oasx_args(self, groups):
        """把全局推送渠道作为虚拟配置项暴露给前端。

        渠道内容保存在 config/notify_channel.yaml，所有脚本配置共用，
        不写进各自的 config json，因此这里只读当前内容展示。
        """
        from module.notify.channel import load_notify_channel

        items = groups.get('error')
        if not isinstance(items, list):
            return groups
        items.append({
            'name': 'notify_config',
            'title': 'notify_config',
            'description': 'notify_config_help',
            'default': '',
            'value': load_notify_channel(),
            'type': 'multi_line',
        })
        return groups

    def select_oasx_arg(self, group, argument, value):
        """接管推送渠道的写入；未接管的参数返回 None，交给默认逻辑。"""
        if group != 'error' or argument != 'notify_config':
            return None
        from module.logger import logger
        from module.notify.channel import save_notify_channel

        try:
            save_notify_channel(str(value))
        except Exception as exc:
            logger.warning(f'Save notify channel failed: {exc}')
            return False
        return True