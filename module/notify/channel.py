# This Python file uses the following encoding: utf-8
"""全局唯一的推送渠道配置。

渠道内容（含 smtp 授权码等敏感值）统一存放在 `config/notify_channel.yaml`，
该文件已被 gitignore（`config/*.yaml`）。各脚本配置里只保留 `notify_enable`
开关，不再各自保存渠道内容；改渠道只需改这一个文件。
"""
import json
from pathlib import Path

import yaml

from module.logger import logger

CHANNEL_FILE = 'notify_channel.yaml'

DEFAULT_CHANNEL = 'provider: null'

CHANNEL_TEMPLATE = """\
# 全局推送渠道配置（所有脚本配置共用；notify_enable 仍按各自配置控制）
# YAML 格式，示例（QQ 邮箱 smtp）：
# provider: smtp
# host: smtp.qq.com
# port: 465
# user: 发件邮箱
# password: SMTP授权码   # 邮箱设置里开启 SMTP 服务后生成，不是登录密码
# To: 收件邮箱           # 不填表示发给发件邮箱自己
# 带截图的推送（如僵尸寮结算截图）只支持 smtp，截图内嵌在正文里。
provider: null
"""


def channel_path() -> Path:
    return Path.cwd() / 'config' / CHANNEL_FILE


def _legacy_channel_from_configs() -> str | None:
    """迁移用：从旧配置文件的 script.error.notify_config 里取一个有效渠道内容。"""
    for path in sorted((Path.cwd() / 'config').glob('*.json')):
        if path.stem.startswith('template'):
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        value = data.get('script', {}).get('error', {}).get('notify_config')
        if not isinstance(value, str):
            continue
        if value.strip() and 'provider: null' not in value:
            logger.info(f'Migrate notify channel from legacy config: {path.name}')
            return value
    return None


def load_notify_channel() -> str:
    """读取全局渠道配置内容；文件缺失时生成（优先沿用旧配置里的渠道）并返回。"""
    path = channel_path()
    if not path.exists():
        legacy = _legacy_channel_from_configs()
        if legacy:
            content = CHANNEL_TEMPLATE.replace('provider: null\n', '') + legacy.strip() + '\n'
        else:
            content = CHANNEL_TEMPLATE
        try:
            path.write_text(content, encoding='utf-8')
            logger.info(f'Notify channel file created: {path}')
        except OSError as exc:
            logger.warning(f'Cannot create notify channel file {path}: {exc}')
        return content
    try:
        return path.read_text(encoding='utf-8')
    except OSError as exc:
        logger.warning(f'Cannot read notify channel file {path}: {exc}')
        return DEFAULT_CHANNEL


def save_notify_channel(content: str) -> None:
    """写入全局渠道配置；写入前要求内容是合法 YAML。"""
    list(yaml.safe_load_all(content or ''))
    channel_path().write_text(content, encoding='utf-8')
    logger.info('Notify channel file saved')
