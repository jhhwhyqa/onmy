# This Python file uses the following encoding: utf-8
"""纳物库统计（`log/storage_stats`）的 HTTP 接口。

数据由 `tasks/DailyTrifles/script_task.py` 的 `run_storage_stats()` 落盘，
读取服务见 `module.server.storage_stats_service`。只提供「每个日期最后一次」的数据与截图。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from module.server.api_logger import ApiLoggingRoute
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
