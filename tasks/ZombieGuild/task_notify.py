# This Python file uses the following encoding: utf-8
"""任务级通知适配层。

本仓库没有 `module/notify/task_notify.py`，全局通知走 `script.error.notify_config`
这条（构造方式见 module/config/config.py 里的 `Notifier(...)`）。

这里提供同名函数，返回带 `enable / push / push_images` 的对象，
让调用侧写法保持不变。

注意：仓库现有的 Notifier 只支持文字推送，不支持发图；`push_images`
退化为"记日志 + 发一条文字通知"，不会静默丢弃。
"""
from module.logger import logger
from module.notify.notify import Notifier


class TaskNotifier:
    """Notifier 的薄封装，补齐调用侧用到的 push_images。"""

    def __init__(self, notifier: Notifier, enable: bool) -> None:
        self._notifier = notifier
        self.enable = enable

    def push(self, title: str = '', content: str = '', **kwargs) -> bool:
        if not self.enable:
            return False
        try:
            return bool(self._notifier.push(title=title, content=content, **kwargs))
        except Exception as exc:
            logger.warning(f'推送通知失败: {exc}')
            return False

    def push_images(self, images, title: str = '', **kwargs) -> bool:
        # 现有 Notifier 发不了图，退化成文字通知，避免静默丢弃
        paths = [str(p) for p in (images or [])]
        logger.info(f'Notifier 不支持发图，已保存 {len(paths)} 张: {paths}')
        return self.push(title=title, content='\n'.join(paths))


def resolve_task_notifier(config, task_cfg=None) -> TaskNotifier:
    """按"任务级开关 + 全局通知配置"得到一个可用的通知器。

    :param config: 当前 Config 对象
    :param task_cfg: 任务自己的通知配置（只有一个 enable 开关）
    """
    enable = bool(getattr(task_cfg, 'enable', False))
    notifier = Notifier('', enable=False)
    if enable:
        try:
            global_cfg = config.model.script.error
            notifier = Notifier(
                global_cfg.notify_config,
                enable=bool(global_cfg.notify_enable),
            )
        except Exception as exc:
            logger.warning(f'初始化通知器失败，通知已禁用: {exc}')
    return TaskNotifier(notifier, enable and notifier.enable)
