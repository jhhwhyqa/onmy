# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

import onepush.core
import yaml
from onepush import get_notifier
from onepush.core import Provider
from onepush.exceptions import OnePushException
from onepush.providers.custom import Custom
from requests import Response
from smtplib import SMTPResponseException

from module.logger import logger
onepush.core.log = logger


class Notifier:
    def __init__(self, _config: str, enable: bool=False) -> None:
        self.config_name: str = ""
        self.provider_name: str = ""
        self.notifier: Provider = None
        self.enable: bool = enable

        if not self.enable:
            return
        config = {}
        try:
            for item in yaml.safe_load_all(_config):
                config.update(item)
        except Exception as e:
            logger.error("Fail to load onepush config, skip sending")
            return
        self.config = config
        try:
            # 获取provider
            self.provider_name: str = self.config.pop("provider", None)
            if self.provider_name is None:
                logger.info("No provider specified, skip sending")
                return
            # 获取notifier
            self.notifier: Provider = get_notifier(self.provider_name)
            # 获取notifier的必填参数
            self.required: list[str] = self.notifier.params["required"]
        except OnePushException:
            logger.exception("Init notifier failed")
            return
        except Exception as e:
            logger.exception(e)
            return

    @property
    def supports_images(self) -> bool:
        """目前只有 smtp 渠道（例如 QQ 邮箱）支持把图片内嵌进正文。"""
        return (self.enable and self.notifier is not None
                and self.provider_name.lower() == "smtp")

    @staticmethod
    def _inline_image_cid(index: int) -> str:
        """内嵌图片的 Content-ID，正文用 `cid:` 引用同一个值。"""
        return f"oas-image-{index}@oas.local"

    def _build_mail_message(self, title: str, content: str, images, filenames=None):
        """为 smtp 渠道拼一封图片内嵌在正文里的邮件，交给 onepush 直接发送。

        onepush 的 smtp provider 支持传入自定义 Message，这里用它绕开默认的
        纯文本解析器。截图以 Content-ID 内联在 HTML 正文中
        （`Content-Disposition: inline`），收件客户端渲染正文即可看到，
        不再出现在附件区。
        """
        from email.message import EmailMessage
        from html import escape

        message = EmailMessage()
        message["Subject"] = title
        sender = self.config.get("From") or self.config.get("user")
        receiver = self.config.get("To") or sender
        if sender:
            message["From"] = sender
        if receiver:
            message["To"] = receiver

        names = list(filenames or [])

        def _name(index: int) -> str:
            if index <= len(names) and names[index - 1]:
                return str(names[index - 1])
            return f"reward_{index}.png"

        # 正文做 HTML 转义，避免日志内容里的尖括号被当成标签；
        # 调用方习惯用 <br> 换行，这里先还原成换行再统一转换。
        text = escape((content or "").replace("<br>", "\n")).replace("\n", "<br>\n")
        pictures = "".join(
            f'<div><img src="cid:{self._inline_image_cid(index)}" '
            f'alt="{escape(_name(index), quote=True)}" style="max-width:100%"></div>'
            for index in range(1, len(images) + 1)
        )
        message.set_content(
            f"<html><body><div>{text}</div>{pictures}</body></html>",
            subtype="html",
        )

        for index, image in enumerate(images, start=1):
            # add_related 会设为 inline 并写 Content-ID，正文才能用 cid: 引用到
            message.add_related(
                bytes(image),
                maintype="image",
                subtype="png",
                cid=f"<{self._inline_image_cid(index)}>",
            )
        return message

    def push(self, images: list = None, filenames: list = None, **kwargs) -> bool:
        if not self.enable or self.notifier is None:
            return False
        # 更新配置
        kwargs["title"] = f"{self.config_name} {kwargs['title']}"
        self.config.update(kwargs)
        # pre check
        for key in self.required:
            if key not in self.config:
                logger.warning(
                    f"Notifier {self.notifier} require param '{key}' but not provided"
                )


        if isinstance(self.notifier, Custom):
            if "method" not in self.config or self.config["method"] == "post":
                self.config["datatype"] = "json"
            if not ("data" in self.config or isinstance(self.config["data"], dict)):
                self.config["data"] = {}
            if "title" in kwargs:
                self.config["data"]["title"] = kwargs["title"]
            if "content" in kwargs:
                self.config["data"]["content"] = kwargs["content"]

        if self.provider_name.lower() == "gocqhttp":
            access_token = self.config.get("access_token")
            if access_token:
                self.config["token"] = access_token


        # 内嵌图片只在本次调用生效，不能写回 self.config 污染后续推送
        payload = self.config
        if images and self.supports_images:
            payload = dict(self.config)
            payload["msg"] = self._build_mail_message(
                kwargs["title"], kwargs.get("content", ""), images, filenames)

        try:
            resp = self.notifier.notify(**payload)
            if isinstance(resp, Response):
                if resp.status_code != 200:
                    logger.warning("Push notify failed!")
                    logger.warning(f"HTTP Code:{resp.status_code}")
                    return False
                else:
                    if self.provider_name.lower() == "gocqhttp":
                        return_data: dict = resp.json()
                        if return_data["status"] == "failed":
                            logger.warning("Push notify failed!")
                            logger.warning(
                                f"Return message:{return_data['wording']}")
                            return False
            elif isinstance(resp, dict) and resp:
                # smtp 发送成功时返回被拒收的收件人，非空即表示没送到
                logger.warning("Push notify failed!")
                logger.warning(f"Refused recipients: {resp}")
                return False
        except SMTPResponseException as e:
            # 认证失败、收件人被拒等都走这个分支，必须算发送失败:
            # 否则调用侧会当作成功，把其实没发出去的截图删掉。
            logger.warning(f"SMTP push failed: {e}")
            return False
        except OnePushException:
            logger.exception("Push notify failed")
            return False
        except Exception as e:
            logger.exception(e)
            return False

        logger.info("Push notify success")
        return True



