# This Python file uses the following encoding: utf-8
"""纳物库统计（`log/storage_stats`）的清理服务。

读取侧（`module.server.storage_stats_service`）对每个日期只认**时间戳最大**的那一份，
所以同一天的其它快照是不可达的死数据；本模块据此提供两层清理：

1. **同日去重**：每个日期只保留最后一次运行，其余 json 与截图一并删除。
2. **按保留期清理**：截图与数据各有独立保留天数，另可选「每周只留某一天」的瘦身规则。

两条硬保护，保证读取侧的语义不被破坏：

- 每个实例**最新的一份快照永不删除** —— 这是对比基准的最后一道保险，
  让 `previousDay`（「最近一天有数据」的对比规则）永远有落点。
- **最近 `min_keep_days` 天**整段跳过，不参与保留期与每周瘦身。

注意 `min_keep_days` 只挡住「保留期」与「每周瘦身」；**同日去重对所有日期生效**，
因为同一天的更早运行在读取侧永远不可达，删掉不改变任何已展示的数据。

清理是纯文件操作：`plan_cleanup()` 只产出计划，`apply_cleanup()` 才真正落盘。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from module.server.storage_stats_service import (
    STORAGE_STATS_ROOT,
    iter_snapshots,
    safe_path,
)

#: 同一天更早的运行：读取侧不可达的死数据。
REASON_SAME_DAY = "same_day_duplicate"

#: 截图超出保留期。
REASON_IMAGE = "image_expired"

#: 数据超出保留期，整个日期一起删除。
REASON_DATA = "data_expired"

#: 每周瘦身：该日期不是要保留的星期几。
REASON_WEEKLY = "weekly_thin"

_DEFAULT_IMAGE_KEEP_DAYS = 90
_DEFAULT_DATA_KEEP_DAYS = 0
_DEFAULT_MIN_KEEP_DAYS = 7


@dataclass(frozen=True)
class CleanupOptions:
    """一次清理的参数。

    Attributes:
        image_keep_days: 截图保留天数，`0` 表示永久保留。
        data_keep_days: 数据保留天数（整个日期一起删），`0` 表示永久保留。
        weekly_keep_weekday: 每周只保留该星期几的数据（ISO 星期，1=周一 … 7=周日），
            `0` 表示不做每周瘦身。
        min_keep_days: 最近 N 天整段跳过，不参与保留期与每周瘦身。
        drop_same_day_runs: 每个日期是否只保留最后一次运行。
    """

    image_keep_days: int = _DEFAULT_IMAGE_KEEP_DAYS
    data_keep_days: int = _DEFAULT_DATA_KEEP_DAYS
    weekly_keep_weekday: int = 0
    min_keep_days: int = _DEFAULT_MIN_KEEP_DAYS
    drop_same_day_runs: bool = True

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "CleanupOptions":
        """从请求体构造参数，缺省与越界都收敛到合法区间。

        Args:
            payload: 请求体字典，允许为 `None`。

        Returns:
            收敛后的清理参数。
        """

        data = dict(payload or {})
        return cls(
            image_keep_days=_clamp_int(
                data.get("image_keep_days"), _DEFAULT_IMAGE_KEEP_DAYS, 0, 3650
            ),
            data_keep_days=_clamp_int(
                data.get("data_keep_days"), _DEFAULT_DATA_KEEP_DAYS, 0, 3650
            ),
            weekly_keep_weekday=_clamp_int(data.get("weekly_keep_weekday"), 0, 0, 7),
            min_keep_days=_clamp_int(
                data.get("min_keep_days"), _DEFAULT_MIN_KEEP_DAYS, 0, 365
            ),
            drop_same_day_runs=bool(data.get("drop_same_day_runs", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        """转成可直接放进响应的字典。"""

        return asdict(self)


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    """把任意输入收敛成 `[low, high]` 区间内的整数。"""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _parse_day(day: str) -> date | None:
    """解析 `YYYY-MM-DD`，无法解析时返回 `None`。"""

    try:
        return date.fromisoformat(day)
    except ValueError:
        return None


def _cutoff(today: date, keep_days: int) -> date | None:
    """算出保留期的分界日：早于该日期的内容会被删除。"""

    if keep_days <= 0:
        return None
    return today - timedelta(days=keep_days)


def _resolve_instances(instance: str) -> list[Path]:
    """列出要清理的实例目录。

    Args:
        instance: 实例目录名；留空表示全部实例。

    Returns:
        实例目录列表。

    Raises:
        StorageStatsError: 实例名非法或路径越界。
    """

    if not STORAGE_STATS_ROOT.is_dir():
        return []
    if instance:
        target = safe_path(instance)
        return [target] if target.is_dir() else []
    return [
        item
        for item in sorted(STORAGE_STATS_ROOT.iterdir(), key=lambda p: p.name)
        if item.is_dir()
    ]


def _run_files(json_path: Path) -> list[Path]:
    """一次运行落盘的文件：json 本体 + 配套截图（存在时）。"""

    files = [json_path]
    image = json_path.with_suffix(".png")
    if image.is_file():
        files.append(image)
    return files


def _relative(path: Path) -> str | None:
    """转成相对 `STORAGE_STATS_ROOT` 的 POSIX 路径，越界时返回 `None`。"""

    try:
        return path.resolve().relative_to(STORAGE_STATS_ROOT).as_posix()
    except (OSError, ValueError):
        return None


def _file_size(path: Path) -> int | None:
    """文件字节数，取不到时返回 `None`。"""

    try:
        return path.stat().st_size
    except OSError:
        return None


def _expiry_reason(
    day: date | None,
    data_cutoff: date | None,
    weekly_keep_weekday: int,
) -> str | None:
    """整日删除的原因，`None` 表示该日期保留。"""

    if day is None:
        # 文件名里的日期无法解析：宁可留着让人工处理，也不猜。
        return None
    if data_cutoff is not None and day < data_cutoff:
        return REASON_DATA
    if weekly_keep_weekday and day.isoweekday() != weekly_keep_weekday:
        return REASON_WEEKLY
    return None


def _plan_instance(
    instance_dir: Path,
    options: CleanupOptions,
    image_cutoff: date | None,
    data_cutoff: date | None,
    protect_from: date,
) -> dict[str, Any] | None:
    """为单个实例生成清理计划，没有可删内容时返回 `None`。"""

    snapshots = iter_snapshots(instance_dir)
    if not snapshots:
        return None

    by_date: dict[str, list[tuple[str, Path]]] = {}
    for day, stamp, json_path in snapshots:
        by_date.setdefault(day, []).append((stamp, json_path))

    newest_date = max(by_date)
    kept_dates: list[str] = []
    dropped_dates: list[str] = []
    pending: list[tuple[Path, str, str]] = []

    for day in sorted(by_date, reverse=True):
        runs = sorted(by_date[day])
        parsed = _parse_day(day)
        protected = day == newest_date or (parsed is not None and parsed >= protect_from)

        reason = (
            None
            if protected
            else _expiry_reason(parsed, data_cutoff, options.weekly_keep_weekday)
        )
        if reason is not None:
            # 整日删除必须清掉该日期的**全部**运行：只删最后一次的话，
            # 读取侧会退回到更早的那次，日期依旧留在列表里。
            dropped_dates.append(day)
            for _, json_path in runs:
                for path in _run_files(json_path):
                    pending.append((path, day, reason))
            continue

        kept_dates.append(day)
        if options.drop_same_day_runs:
            for _, json_path in runs[:-1]:
                for path in _run_files(json_path):
                    pending.append((path, day, REASON_SAME_DAY))
        if (
            not protected
            and image_cutoff is not None
            and parsed is not None
            and parsed < image_cutoff
        ):
            pending.append((runs[-1][1].with_suffix(".png"), day, REASON_IMAGE))

    deletions: list[dict[str, Any]] = []
    for path, day, reason in pending:
        relative = _relative(path)
        if relative is None:
            continue
        size = _file_size(path)
        if size is None:
            # 计划生成期间文件已经不在（并发删除等），不报幽灵条目。
            continue
        deletions.append(
            {
                "path": relative,
                "date": day,
                "kind": "image" if path.suffix.lower() == ".png" else "data",
                "reason": reason,
                "bytes": size,
            }
        )

    if not deletions and not dropped_dates:
        return None
    return {
        "instance": instance_dir.name,
        "kept_dates": kept_dates,
        "dropped_dates": dropped_dates,
        "deletions": deletions,
    }


def plan_cleanup(options: CleanupOptions, instance: str = "") -> dict[str, Any]:
    """生成清理计划，不触碰任何文件。

    Args:
        options: 清理参数。
        instance: 只清理该实例；留空表示全部实例。

    Returns:
        计划字典，含逐文件删除项与汇总。
    """

    today = date.today()
    image_cutoff = _cutoff(today, options.image_keep_days)
    data_cutoff = _cutoff(today, options.data_keep_days)
    protect_from = today - timedelta(days=max(options.min_keep_days - 1, 0))

    instances = [
        report
        for instance_dir in _resolve_instances(instance)
        if (
            report := _plan_instance(
                instance_dir, options, image_cutoff, data_cutoff, protect_from
            )
        )
        is not None
    ]

    return {
        "dry_run": True,
        "options": options.as_dict(),
        "today": today.isoformat(),
        "protect_from": protect_from.isoformat(),
        "totals": {
            "files": sum(len(item["deletions"]) for item in instances),
            "bytes": sum(
                entry["bytes"] for item in instances for entry in item["deletions"]
            ),
            "instances": len(instances),
        },
        "instances": instances,
    }


def _prune_empty_dirs(root: Path) -> None:
    """自底向上删掉空目录，保留 `root` 自身。"""

    if not root.is_dir():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_dir():
            continue
        try:
            if not any(path.iterdir()):
                path.rmdir()
        except OSError:
            # 清理失败不能影响 OAS 正常运行
            pass


def apply_cleanup(options: CleanupOptions, instance: str = "") -> dict[str, Any]:
    """按 [options] 重新生成计划并执行删除。

    计划在服务端重新计算而不是由调用方回传路径，避免信任客户端给出的文件路径。

    Args:
        options: 清理参数。
        instance: 只清理该实例；留空表示全部实例。

    Returns:
        计划字典，额外带上 `deleted` 与 `failed`。
    """

    report = plan_cleanup(options, instance)
    report["dry_run"] = False

    deleted_files = 0
    deleted_bytes = 0
    failed: list[dict[str, str]] = []

    for item in report["instances"]:
        for entry in item["deletions"]:
            target = (STORAGE_STATS_ROOT / entry["path"]).resolve()
            try:
                target.relative_to(STORAGE_STATS_ROOT)
            except ValueError:
                failed.append({"path": entry["path"], "error": "路径越界"})
                continue
            if not target.is_file():
                continue
            try:
                target.unlink()
            except OSError as exc:
                failed.append({"path": entry["path"], "error": str(exc)})
                continue
            deleted_files += 1
            deleted_bytes += entry["bytes"]
        _prune_empty_dirs(safe_path(item["instance"]))

    report["deleted"] = {
        "files": deleted_files,
        "bytes": deleted_bytes,
        "instances": len(report["instances"]),
    }
    report["failed"] = failed
    return report
