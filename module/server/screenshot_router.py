# This Python file uses the following encoding: utf-8
"""脚本最近一次截图（`log/screenshot_last`）的 HTTP 接口。

截图由 `module/device/screenshot.py` 的 `save_latest_screenshot()` 覆盖式落盘：
文件名是配置名，每个配置只保留最新一张，脚本退出后文件保留，
所以这里读到的就是「脚本上一次对模拟器的截图」。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from module.device.screenshot import sanitize_instance_name
from module.server.api_logger import ApiLoggingRoute
from module.server.log_service import LOG_ROOT

screenshot_app = APIRouter(
    prefix="/screenshot",
    tags=["screenshot"],
    route_class=ApiLoggingRoute,
)

LAST_SCREENSHOT_ROOT = (LOG_ROOT / "screenshot_last").resolve()


@screenshot_app.get('/last')
async def screenshot_last(instance: str):
    """返回某配置最近一次落盘的截图（png）。

    Args:
        instance: 配置名，与脚本配置（`script.name`）一致。

    Raises:
        HTTPException: 名称为空/含非法字符（400），或该配置还没有截图（404）。
    """

    name = sanitize_instance_name(instance)
    if not name or name in ('.', '..'):
        raise HTTPException(
            status_code=400,
            detail={'code': 'invalid_name', 'message': f'非法名称: {instance!r}'},
        )

    target = (LAST_SCREENSHOT_ROOT / f'{name}.png').resolve()
    try:
        target.relative_to(LAST_SCREENSHOT_ROOT)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={'code': 'invalid_path', 'message': '路径越界'},
        ) from exc

    if not target.is_file():
        raise HTTPException(
            status_code=404,
            detail={'code': 'not_found', 'message': f'暂无截图: {instance}'},
        )

    return FileResponse(target, media_type='image/png')
