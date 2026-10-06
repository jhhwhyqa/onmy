# This Python file uses the following encoding: utf-8
"""纳物库统计（`log/storage_stats`）的 HTTP 接口。

数据由 `tasks/DailyTrifles/script_task.py` 的 `run_storage_stats()` 落盘，
读取服务见 `module.server.storage_stats_service`。只提供「每个日期最后一次」的数据与截图。

清理服务见 `module.server.storage_stats_cleanup`，通过 `POST /storage_stats/cleanup` 暴露；
默认 `dry_run=true` 只回计划，调用方确认后再带 `dry_run=false` 执行。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from module.server.api_logger import ApiLoggingRoute
from module.server.storage_stats_cleanup import CleanupOptions, apply_cleanup, plan_cleanup
from module.server.storage_stats_service import (
    StorageStatsError,
    daily_latest,
    daily_series,
    latest_image_path,
    list_instances,
)

storage_stats_app = APIRouter(
    prefix="/storage_stats",
    tags=["storage_stats"],
    route_class=ApiLoggingRoute,
)


class StorageDayRecord(BaseModel):
    """某一天最后一次统计。"""

    instance: str = Field(description="实例目录名（配置名经过文件名安全化后的结果）")
    date: str = Field(description="日期, YYYY-MM-DD")
    timestamp: str = Field(description="该日期最后一次落盘的时间戳, 形如 2026-10-05_19-28-23")
    image: str | None = Field(default=None, description="配套截图文件名; 缺图时为 null")
    image_url: str | None = Field(default=None, description="读取该截图的接口 URL; 缺图时为 null")
    data: dict[str, Any] = Field(description="统计结果, 键为资源名(蓝票/御札…), 值为数量")


class StorageInstanceSeries(BaseModel):
    """单个实例每天最后一次统计的序列（新到旧）。"""

    instance: str = Field(description="实例目录名")
    days: list[StorageDayRecord] = Field(default_factory=list, description="按日期新到旧排列")


class StorageInstanceItem(BaseModel):
    """实例索引项。"""

    name: str = Field(description="实例目录名")
    dates: list[str] = Field(default_factory=list, description="该实例有数据的日期, 新到旧")


class StorageInstanceList(BaseModel):
    """实例索引响应。"""

    instances: list[StorageInstanceItem] = Field(default_factory=list)


class StorageCleanupOptions(BaseModel):
    """清理参数。"""

    image_keep_days: int = Field(
        default=90, ge=0, le=3650, description="截图保留天数, 0 = 永久保留"
    )
    data_keep_days: int = Field(
        default=0, ge=0, le=3650, description="数据保留天数, 0 = 永久保留"
    )
    weekly_keep_weekday: int = Field(
        default=0,
        ge=0,
        le=7,
        description="每周只保留该星期几的数据(ISO 星期, 1=周一 … 7=周日), 0 = 不瘦身",
    )
    min_keep_days: int = Field(
        default=7, ge=0, le=365, description="最近 N 天整段跳过, 不参与保留期与每周瘦身"
    )
    drop_same_day_runs: bool = Field(
        default=True, description="每个日期只保留最后一次运行"
    )


class StorageCleanupRequest(StorageCleanupOptions):
    """清理请求：参数 + 作用范围 + 是否只预览。"""

    instance: str = Field(default="", description="只清理该实例; 留空表示全部实例")
    dry_run: bool = Field(default=True, description="true 只回计划, false 执行删除")


class StorageCleanupDeletion(BaseModel):
    """一条待删除的文件。"""

    path: str = Field(description="相对 log/storage_stats 的 POSIX 路径")
    date: str = Field(description="所属日期, YYYY-MM-DD")
    kind: str = Field(description="文件类型: image | data")
    reason: str = Field(
        description="删除原因: same_day_duplicate | image_expired | data_expired | weekly_thin"
    )
    bytes: int = Field(description="文件字节数")


class StorageCleanupInstance(BaseModel):
    """单个实例的清理计划。"""

    instance: str = Field(description="实例目录名")
    kept_dates: list[str] = Field(default_factory=list, description="清理后保留的日期")
    dropped_dates: list[str] = Field(default_factory=list, description="整日删除的日期")
    deletions: list[StorageCleanupDeletion] = Field(
        default_factory=list, description="待删除的文件, 新到旧"
    )


class StorageCleanupTotals(BaseModel):
    """文件与字节数汇总。"""

    files: int = Field(default=0)
    bytes: int = Field(default=0)
    instances: int = Field(default=0)


class StorageCleanupReport(BaseModel):
    """清理计划 / 执行结果。"""

    dry_run: bool = Field(description="true 表示这只是计划, 未删除任何文件")
    options: StorageCleanupOptions = Field(description="本次实际生效的参数")
    today: str = Field(description="服务端当天日期, YYYY-MM-DD")
    protect_from: str = Field(description="保护窗口起始日, 该日及之后一律不动")
    totals: StorageCleanupTotals = Field(description="计划删除量")
    instances: list[StorageCleanupInstance] = Field(default_factory=list)
    deleted: StorageCleanupTotals | None = Field(
        default=None, description="实际删除量; dry_run 时为 null"
    )
    failed: list[dict[str, str]] = Field(
        default_factory=list, description="删除失败的文件与原因"
    )


def _raise_storage_error(exc: StorageStatsError) -> None:
    """把服务层异常转换成 HTTPException。

    Args:
        exc: 服务层抛出的业务异常。
    """

    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


@storage_stats_app.get("", response_model=StorageInstanceList)
async def get_storage_stats_instances():
    """列出所有实例及其有数据的日期。"""
    return list_instances()


@storage_stats_app.post("/cleanup", response_model=StorageCleanupReport)
async def post_storage_stats_cleanup(payload: StorageCleanupRequest):
    """预览或执行纳物库清理。

    默认 `dry_run=true` 只返回计划；确认后再带 `dry_run=false` 才真正删除文件。
    每个实例最新的一份快照与最近 `min_keep_days` 天永不删除。
    """
    options = CleanupOptions.from_payload(payload.model_dump())
    try:
        if payload.dry_run:
            return plan_cleanup(options, payload.instance)
        return apply_cleanup(options, payload.instance)
    except StorageStatsError as exc:
        _raise_storage_error(exc)


@storage_stats_app.get("/{instance}", response_model=StorageInstanceSeries)
async def get_storage_stats_series(
    instance: str = Path(description="实例目录名, 如 原皮 / oas2"),
):
    """读取某实例每个日期最后一次的统计。"""
    try:
        return daily_series(instance)
    except StorageStatsError as exc:
        _raise_storage_error(exc)


@storage_stats_app.get("/{instance}/{date}", response_model=StorageDayRecord)
async def get_storage_stats_latest(
    instance: str = Path(description="实例目录名, 如 原皮 / oas2"),
    date: str = Path(description="日期, YYYY-MM-DD"),
):
    """读取某实例某日期最后一次的统计。"""
    try:
        return daily_latest(instance, date)
    except StorageStatsError as exc:
        _raise_storage_error(exc)


@storage_stats_app.get("/{instance}/{date}/image")
async def get_storage_stats_image(
    instance: str = Path(description="实例目录名, 如 原皮 / oas2"),
    date: str = Path(description="日期, YYYY-MM-DD"),
):
    """读取某实例某日期最后一次统计对应的截图。"""
    try:
        image_path = latest_image_path(instance, date)
    except StorageStatsError as exc:
        _raise_storage_error(exc)
    return FileResponse(str(image_path), media_type="image/png")
