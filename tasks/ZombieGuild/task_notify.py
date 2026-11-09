# This Python file uses the following encoding: utf-8
"""任务级通知适配层。

本仓库没有 `module/notify/task_notify.py`，全局通知走 `script.error.notify_config`
这条（构造方式见 module/config/config.py 里的 `Notifier(...)`）。

这里提供同名函数，返回带 `enable / push / push_images` 的对象，
让调用侧写法保持不变。

注意：`push_images` 只在渠道支持内嵌图片时（smtp，例如 QQ 邮箱）真的把截图发出去，
截图内嵌在正文里而不是放在附件区；其余渠道退化为纯文字通知，不会静默丢弃。
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

    def push_images(self, images, title: str = '', content: str = '',
                    filenames=None, **kwargs) -> bool:
        """把截图内嵌在正文里发送；渠道不支持时退化为文字通知。

        :param images: PNG 字节流列表
        :param filenames: 与 images 一一对应的图片名，用作正文里的插图说明
        """
        if not self.enable:
            return False
        images = list(images or [])
        if images and self._notifier.supports_images:
            return self._notifier.push(title=title, content=content,
                                       images=images, filenames=filenames, **kwargs)
        logger.info(f'当前推送渠道不支持内嵌图片，{len(images)} 张截图未发送，仅推送文字通知')
        return self.push(title=title, content=content, **kwargs)


def resolve_task_notifier(config, enable: bool = False) -> TaskNotifier:
    """按"任务级开关 + 全局通知配置"得到一个可用的通知器。

    :param config: 当前 Config 对象
    :param enable: 本次推送对应开关的状态（结算截图、刷新上限提醒各自独立）
    """
    enable = bool(enable)
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
