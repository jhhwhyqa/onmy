# This Python file uses the following encoding: utf-8
"""纳物库统计（`log/storage_stats`）的读取服务。

数据由 `tasks/DailyTrifles/script_task.py` 的 `run_storage_stats()` 落盘：

- 新布局：`log/storage_stats/{实例名}/{日期}/{时间戳}.json`（配套同名 `.png`）
- 旧布局：`log/storage_stats/{实例名}/{时间戳}.json`（2026-10-05 之前）

对外只提供「**每个日期取最后一次**」的读取：日期取自文件名里的时间戳前缀，
所以两种布局都能扫到，且同一天有多次运行时只返回时间戳最大的那次。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from module.server.log_service import LOG_ROOT

STORAGE_STATS_ROOT = (LOG_ROOT / "storage_stats").resolve()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STAMP_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})$")
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class StorageStatsError(Exception):
    """纳物库统计读取的业务异常。

    Args:
        status_code: 转换成 HTTP 响应时使用的状态码。
        code: 给前端判断错误类型使用的稳定错误码。
        message: 面向调用方的错误说明。
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _safe_path(*parts: str) -> Path:
    """把若干路径片段拼到 STORAGE_STATS_ROOT 下，并校验名称合法且没有越界。

    Args:
        *parts: 相对 STORAGE_STATS_ROOT 的路径片段（如实例名、日期）。

    Returns:
        解析后的绝对路径。

    Raises:
        StorageStatsError: 名称为空/含非法字符，或解析后越出根目录。
    """

    for part in parts:
        if not part or part in (".", "..") or _UNSAFE_NAME_RE.search(part):
            raise StorageStatsError(400, "invalid_name", f"非法名称: {part!r}")
    target = STORAGE_STATS_ROOT.joinpath(*parts).resolve()
    try:
        target.relative_to(STORAGE_STATS_ROOT)
    except ValueError as exc:
        raise StorageStatsError(400, "invalid_path", "路径越界") from exc
    return target


def _check_date(day: str) -> str:
    """校验日期字符串格式。

    Args:
        day: 形如 `2026-10-05` 的日期。

    Returns:
        原样返回的日期字符串。

    Raises:
        StorageStatsError: 格式不是 `YYYY-MM-DD`。
    """

    if not _DATE_RE.match(str(day or "")):
        raise StorageStatsError(400, "invalid_date", "日期格式应为 YYYY-MM-DD")
    return day


def _iter_latest_runs(instance_dir: Path) -> dict[str, tuple[str, Path]]:
    """扫描实例目录，返回 `日期 -> (时间戳, 该日期最后一次的 json 路径)`。

    递归扫描是为了同时兼容 `{实例}/{日期}/{时间戳}.json` 与 `{实例}/{时间戳}.json` 两种布局；
    日期与排序都取自文件名里的时间戳，文件名不符合约定的 json 直接跳过。
    """

    latest: dict[str, tuple[str, Path]] = {}
    if not instance_dir.is_dir():
        return latest
    for path in instance_dir.rglob("*.json"):
        match = _STAMP_RE.match(path.stem)
        if not match:
            continue
        day = match.group("date")
        current = latest.get(day)
        if current is None or path.stem > current[0]:
            latest[day] = (path.stem, path)
    return latest


def _build_day_record(instance: str, day: str, stamp: str, json_path: Path) -> dict[str, Any]:
    """把一次落盘结果组装成响应用的字典（含截图名与截图 URL）。"""

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StorageStatsError(500, "invalid_data", f"统计文件读取失败: {json_path.name}") from exc

    image = json_path.with_suffix(".png")
    image_name = image.name if image.is_file() else None
    return {
        "instance": instance,
        "date": day,
        "timestamp": stamp,
        "image": image_name,
        "image_url": (
            f"/storage_stats/{quote(instance)}/{day}/image" if image_name else None
        ),
        "data": data,
    }


def list_instances() -> dict[str, Any]:
    """列出所有实例及其有数据的日期（新到旧）。"""

    if not STORAGE_STATS_ROOT.is_dir():
        return {"instances": []}
    instances = []
    for instance_dir in sorted(STORAGE_STATS_ROOT.iterdir(), key=lambda p: p.name):
        if not instance_dir.is_dir():
            continue
        dates = sorted(_iter_latest_runs(instance_dir), reverse=True)
        instances.append({"name": instance_dir.name, "dates": dates})
    return {"instances": instances}


def daily_series(instance: str) -> dict[str, Any]:
    """取某实例**每个日期最后一次**的统计，按日期新到旧返回。

    Raises:
        StorageStatsError: 实例目录不存在。
    """

    instance_dir = _safe_path(instance)
    if not instance_dir.is_dir():
        raise StorageStatsError(404, "instance_not_found", f"实例不存在: {instance}")
    latest = _iter_latest_runs(instance_dir)
    days = [
        _build_day_record(instance, day, stamp, json_path)
        for day, (stamp, json_path) in sorted(latest.items(), reverse=True)
    ]
    return {"instance": instance, "days": days}


def daily_latest(instance: str, day: str) -> dict[str, Any]:
    """取某实例某日期最后一次的统计。

    Raises:
        StorageStatsError: 实例目录不存在，或该日期没有数据。
    """

    _check_date(day)
    instance_dir = _safe_path(instance)
    if not instance_dir.is_dir():
        raise StorageStatsError(404, "instance_not_found", f"实例不存在: {instance}")
    latest = _iter_latest_runs(instance_dir).get(day)
    if latest is None:
        raise StorageStatsError(404, "not_found", f"没有该日期的数据: {instance}/{day}")
    return _build_day_record(instance, day, latest[0], latest[1])


def latest_image_path(instance: str, day: str) -> Path:
    """取某实例某日期最后一次统计对应的截图路径。

    Raises:
        StorageStatsError: 实例/日期不存在，或截图文件缺失。
    """

    _check_date(day)
    instance_dir = _safe_path(instance)
    if not instance_dir.is_dir():
        raise StorageStatsError(404, "instance_not_found", f"实例不存在: {instance}")
    latest = _iter_latest_runs(instance_dir).get(day)
    if latest is None:
        raise StorageStatsError(404, "not_found", f"没有该日期的数据: {instance}/{day}")
    image = latest[1].with_suffix(".png")
    if not image.is_file():
        raise StorageStatsError(404, "image_not_found", f"截图不存在: {image.name}")
    return image
