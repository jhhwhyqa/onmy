from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Path as FastAPIPath, Query
from pydantic import BaseModel, Field

from module.server.api_logger import ApiLoggingRoute


# ----------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------

# click_statistics_router.py
#     module/server/
#
# parents[0] = module/server
# parents[1] = module
# parents[2] = OnmyojiAutoScript
#
# 所以这里得到项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CLICK_STATISTICS_ROOT = (
    PROJECT_ROOT
    / "log"
    / "click_statistics"
)


# ----------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------

click_statistics_app = APIRouter(
    prefix="/click-statistics",
    tags=["click-statistics"],
    route_class=ApiLoggingRoute,
)


# ----------------------------------------------------------------------
# Response Models
# ----------------------------------------------------------------------

class ClickStatisticsConfigListResponse(BaseModel):
    configs: list[str] = Field(default_factory=list)


class ClickStatisticsTaskListResponse(BaseModel):
    config: str
    tasks: list[str] = Field(default_factory=list)


class ClickStatisticsDateListResponse(BaseModel):
    config: str
    task: str
    dates: list[str] = Field(default_factory=list)


class ClickStatisticsSessionSummary(BaseModel):
    session_id: str
    task: str

    start_time: str | None = None
    end_time: str | None = None

    duration: float = 0.0

    success: bool = False
    status: str = ""

    total_clicks: int = 0


class ClickStatisticsSessionListResponse(BaseModel):
    config: str
    task: str
    date: str

    sessions: list[ClickStatisticsSessionSummary] = Field(
        default_factory=list
    )


class ClickStatisticsDetailResponse(BaseModel):
    version: int = 1

    task: str
    config_name: str = ""
    session_id: str

    start_time: str | None = None
    end_time: str | None = None

    duration: float = 0.0

    success: bool = False
    status: str = ""

    summary: dict[str, Any] = Field(
        default_factory=dict
    )

    events: list[dict[str, Any]] = Field(
        default_factory=list
    )


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------

def _validate_path_name(
    name: str,
    field_name: str,
) -> str:
    """
    防止通过 URL 参数访问 click_statistics 目录以外的文件。
    """

    name = str(name).strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} cannot be empty",
        )

    if name in {".", ".."}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}",
        )

    if "/" in name or "\\" in name:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}",
        )

    if ".." in name:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}",
        )

    return name


def _validate_date(
    date_text: str,
) -> str:
    try:
        parsed = date.fromisoformat(
            date_text
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid date format, expected YYYY-MM-DD",
        ) from exc

    return parsed.isoformat()


def _read_json(
    path: Path,
) -> dict[str, Any]:
    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Statistics file not found",
        ) from exc

    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON file: {path.name}",
        ) from exc

    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read statistics file: {path.name}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail=f"Invalid statistics data: {path.name}",
        )

    return data


def _config_path(
    config_name: str,
) -> Path:
    config_name = _validate_path_name(
        config_name,
        "config name",
    )

    return (
        CLICK_STATISTICS_ROOT
        / config_name
    )


def _date_path(
    config_name: str,
    date_text: str,
) -> Path:
    config_path = _config_path(
        config_name
    )

    date_text = _validate_date(
        date_text
    )

    return (
        config_path
        / date_text
    )


def _iter_config_dirs() -> list[Path]:
    """
    返回所有 OAS 实例 / 配置目录。

    目录结构：
        log/click_statistics/
            狂蛮/
            实例2/
            实例3/
    """

    if not CLICK_STATISTICS_ROOT.exists():
        return []

    if not CLICK_STATISTICS_ROOT.is_dir():
        return []

    return sorted(
        (
            path
            for path in CLICK_STATISTICS_ROOT.iterdir()
            if path.is_dir()
        ),
        key=lambda path: path.name,
    )


def _iter_date_dirs(
    config_name: str,
) -> list[Path]:
    config_path = _config_path(
        config_name
    )

    if not config_path.exists():
        return []

    return sorted(
        (
            path
            for path in config_path.iterdir()
            if path.is_dir()
        ),
        key=lambda path: path.name,
        reverse=True,
    )


def _find_task_files(
    config_name: str,
    task_name: str,
    date_text: str | None = None,
) -> list[Path]:
    """
    查找指定：
        配置 + 任务 + 日期

    对应：
        click_statistics/
            配置/
                日期/
                    *.json
    """

    config_name = _validate_path_name(
        config_name,
        "config name",
    )

    task_name = _validate_path_name(
        task_name,
        "task name",
    )

    if date_text is not None:
        date_dirs = [
            _date_path(
                config_name,
                date_text,
            )
        ]
    else:
        date_dirs = _iter_date_dirs(
            config_name
        )

    results: list[Path] = []

    for date_dir in date_dirs:
        if not date_dir.exists():
            continue

        for path in date_dir.glob("*.json"):
            if not path.is_file():
                continue

            try:
                data = _read_json(path)
            except HTTPException:
                # 单个损坏文件不影响其他记录
                continue

            if data.get("task") == task_name:
                results.append(path)

    results.sort(
        key=lambda path: path.name,
        reverse=True,
    )

    return results


# ----------------------------------------------------------------------
# 1. 获取所有 OAS 实例 / 配置
#
# GET
# /click-statistics/configs
# ----------------------------------------------------------------------

@click_statistics_app.get(
    "/configs",
    response_model=ClickStatisticsConfigListResponse,
)
async def list_click_statistics_configs():
    configs = [
        path.name
        for path in _iter_config_dirs()
    ]

    return {
        "configs": configs
    }


# ----------------------------------------------------------------------
# 2. 获取某个实例有哪些任务
#
# GET
# /click-statistics/{config_name}/tasks
# ----------------------------------------------------------------------

@click_statistics_app.get(
    "/{config_name}/tasks",
    response_model=ClickStatisticsTaskListResponse,
)
async def list_click_statistics_tasks(
    config_name: str = FastAPIPath(
        description="OAS 配置 / 实例名称"
    ),
):
    config_name = _validate_path_name(
        config_name,
        "config name",
    )

    tasks: set[str] = set()

    for date_dir in _iter_date_dirs(
        config_name
    ):
        for path in date_dir.glob("*.json"):
            if not path.is_file():
                continue

            try:
                data = _read_json(path)
            except HTTPException:
                continue

            task_name = str(
                data.get(
                    "task",
                    "",
                )
            ).strip()

            if task_name:
                tasks.add(task_name)

    return {
        "config": config_name,
        "tasks": sorted(tasks),
    }


# ----------------------------------------------------------------------
# 3. 获取某个实例 + 某个任务有哪些日期
#
# GET
# /click-statistics/{config_name}/{task_name}/dates
# ----------------------------------------------------------------------

@click_statistics_app.get(
    "/{config_name}/{task_name}/dates",
    response_model=ClickStatisticsDateListResponse,
)
async def list_click_statistics_dates(
    config_name: str = FastAPIPath(
        description="OAS 配置 / 实例名称"
    ),
    task_name: str = FastAPIPath(
        description="任务名称"
    ),
):
    config_name = _validate_path_name(
        config_name,
        "config name",
    )

    task_name = _validate_path_name(
        task_name,
        "task name",
    )

    dates: list[str] = []

    for date_dir in _iter_date_dirs(
        config_name
    ):
        try:
            date.fromisoformat(
                date_dir.name
            )
        except ValueError:
            continue

        files = _find_task_files(
            config_name,
            task_name,
            date_dir.name,
        )

        if files:
            dates.append(
                date_dir.name
            )

    dates = sorted(
        set(dates),
        reverse=True,
    )

    return {
        "config": config_name,
        "task": task_name,
        "dates": dates,
    }


# ----------------------------------------------------------------------
# 4. 获取某实例 + 某任务 + 某日期的所有运行记录
#
# GET
# /click-statistics/{config_name}/{task_name}?date=2026-09-03
# ----------------------------------------------------------------------

@click_statistics_app.get(
    "/{config_name}/{task_name}",
    response_model=ClickStatisticsSessionListResponse,
)
async def list_click_statistics_sessions(
    config_name: str = FastAPIPath(
        description="OAS 配置 / 实例名称"
    ),
    task_name: str = FastAPIPath(
        description="任务名称"
    ),
    date_text: str = Query(
        ...,
        alias="date",
        description="YYYY-MM-DD",
    ),
):
    config_name = _validate_path_name(
        config_name,
        "config name",
    )

    task_name = _validate_path_name(
        task_name,
        "task name",
    )

    date_text = _validate_date(
        date_text
    )

    files = _find_task_files(
        config_name,
        task_name,
        date_text,
    )

    sessions: list[
        ClickStatisticsSessionSummary
    ] = []

    for path in files:
        try:
            data = _read_json(path)
        except HTTPException:
            continue

        summary = data.get(
            "summary",
            {},
        )

        if not isinstance(
            summary,
            dict,
        ):
            summary = {}

        events = data.get(
            "events",
            [],
        )

        if not isinstance(
            events,
            list,
        ):
            events = []

        total_clicks = int(
            summary.get(
                "total_clicks",
                len(events),
            )
        )

        sessions.append(
            ClickStatisticsSessionSummary(
                session_id=str(
                    data.get(
                        "session_id",
                        path.stem,
                    )
                ),
                task=str(
                    data.get(
                        "task",
                        task_name,
                    )
                ),
                start_time=data.get(
                    "start_time"
                ),
                end_time=data.get(
                    "end_time"
                ),
                duration=float(
                    data.get(
                        "duration",
                        0.0,
                    )
                ),
                success=bool(
                    data.get(
                        "success",
                        False,
                    )
                ),
                status=str(
                    data.get(
                        "status",
                        "",
                    )
                ),
                total_clicks=total_clicks,
            )
        )

    sessions.sort(
        key=lambda item: (
            item.start_time or ""
        ),
        reverse=True,
    )

    return {
        "config": config_name,
        "task": task_name,
        "date": date_text,
        "sessions": sessions,
    }


# ----------------------------------------------------------------------
# 5. 获取某一次任务完整点击数据
#
# GET
# /click-statistics/{config_name}/{task_name}/{date}/{session_id}
# ----------------------------------------------------------------------

@click_statistics_app.get(
    "/{config_name}/{task_name}/{date_text}/{session_id}",
    response_model=ClickStatisticsDetailResponse,
)
async def get_click_statistics_detail(
    config_name: str = FastAPIPath(
        description="OAS 配置 / 实例名称"
    ),
    task_name: str = FastAPIPath(
        description="任务名称"
    ),
    date_text: str = FastAPIPath(
        description="YYYY-MM-DD"
    ),
    session_id: str = FastAPIPath(
        description="Session ID"
    ),
):
    config_name = _validate_path_name(
        config_name,
        "config name",
    )

    task_name = _validate_path_name(
        task_name,
        "task name",
    )

    session_id = _validate_path_name(
        session_id,
        "session id",
    )

    date_text = _validate_date(
        date_text
    )

    date_dir = _date_path(
        config_name,
        date_text,
    )

    if not date_dir.exists():
        raise HTTPException(
            status_code=404,
            detail="Statistics date not found",
        )

    # Session ID 在文件名最前面：
    #
    # 000001_004110_167_BondlingFairyland.json
    #
    # 所以直接使用：
    #
    # 000001_004110_167_*.json
    candidates = []

    for path in date_dir.glob(
        f"{session_id}_*.json"
    ):
        if not path.is_file():
            continue

        try:
            data = _read_json(path)
        except HTTPException:
            continue

        if (
            data.get("task") == task_name
            and str(
                data.get(
                    "session_id",
                    "",
                )
            ) == session_id
        ):
            candidates.append(path)

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail="Statistics session not found",
        )

    # 正常情况下一个 session 只有一个文件
    path = candidates[0]

    data = _read_json(path)

    summary = data.get(
        "summary",
        {},
    )

    if not isinstance(
        summary,
        dict,
    ):
        summary = {}

    events = data.get(
        "events",
        [],
    )

    if not isinstance(
        events,
        list,
    ):
        events = []

    return {
        "version": int(
            data.get(
                "version",
                1,
            )
        ),
        "task": str(
            data.get(
                "task",
                task_name,
            )
        ),
        "config_name": str(
            data.get(
                "config_name",
                config_name,
            )
        ),
        "session_id": str(
            data.get(
                "session_id",
                session_id,
            )
        ),
        "start_time": data.get(
            "start_time"
        ),
        "end_time": data.get(
            "end_time"
        ),
        "duration": float(
            data.get(
                "duration",
                0.0,
            )
        ),
        "success": bool(
            data.get(
                "success",
                False,
            )
        ),
        "status": str(
            data.get(
                "status",
                "",
            )
        ),
        "summary": summary,
        "events": events,
    }