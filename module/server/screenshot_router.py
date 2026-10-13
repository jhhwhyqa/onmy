# This Python file uses the following encoding: utf-8
"""脚本实时画面的 WebSocket 接口。

画面取自 `module/image` 的图像服务：脚本每次截图都会 `register_frame()` 把当前帧注册
进去，这里只是把它读回来，**既不触发截图也不落盘**，所以可以和正在运行的脚本同时使用。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from module.image.rpc import get_image_client
from module.logger import logger
from module.server.api_logger import ApiLoggingRoute, log_ws_event

screenshot_app = APIRouter(
    prefix="/screenshot",
    tags=["screenshot"],
    route_class=ApiLoggingRoute,
)

# 实时预览的轮询间隔（秒）。预览只用来「看脚本在做什么」，不需要跟手，所以取
# 2 秒一次（0.5fps）。脚本最快 0.1 秒一帧，按这个节奏读取时每次轮询几乎必然拿到
# 新帧，但每秒只编码 0.5 次，zerorpc 往返与 JPEG 编码开销都降到 4fps 时的八分之一。
LIVE_POLL_INTERVAL = 2.0


def _normalize_live_instance(instance: str) -> str:
    """规整实时预览用的配置名。

    这里**不能**做文件名清洗（把 `/` 之类的字符替换成 `_`）：那是为了得到合法文件名，
    而内存里的 `config_name` 是脚本注册帧时的原始值（`screenshot.py` 的
    `register_frame()` 直接传 `config.config_name`），替换过之后就会查不到帧。

    Args:
        instance: 原始配置名。

    Returns:
        str: 去掉首尾空白后的配置名。

    Raises:
        HTTPException: 配置名为空（400）。
    """

    name = str(instance or '').strip()
    if not name:
        raise HTTPException(
            status_code=400,
            detail={'code': 'invalid_name', 'message': f'非法名称: {instance!r}'},
        )
    return name


def _read_live_frame(config_name: str) -> dict[str, Any] | None:
    """从图像服务读一帧；读不到时返回 None。

    帧是脚本截图时注册进图像服务的，所以读取本身不触发任何截图，也不碰模拟器。

    Args:
        config_name: 脚本配置名。

    Returns:
        dict | None: 图像服务返回的帧信息；连接不可用时返回 None。

    Note:
        这个调用是**阻塞**的，必须在事件循环里直接调用，不能丢进 `asyncio.to_thread`：
        zerorpc 客户端基于 gevent，而 gevent 的 hub 是线程局部的，同一个客户端跨线程
        使用会触发 `AssertionError: Can only use Waiter.switch method from the Hub
        greenlet`（已实测复现）。单次读取在缓存命中时只有一次本地往返（约 1~3ms），
        按 `LIVE_POLL_INTERVAL` 的节奏阻塞是可以接受的。
    """

    try:
        return get_image_client().get_config_frame(config_name)
    except Exception as first_error:
        # 图像服务可能重启过，缓存里的旧客户端会一直失败，强制重建再试一次。
        try:
            return get_image_client(refresh=True).get_config_frame(config_name)
        except Exception as retry_error:
            logger.warning(
                f'Failed to read live frame for {config_name}: '
                f'{first_error} / retry: {retry_error}'
            )
            return None


@screenshot_app.websocket('/live/ws/{instance}')
async def screenshot_live_ws(websocket: WebSocket, instance: str):
    """把某个配置的实时画面推给前端。

    帧取自图像服务内存里脚本刚注册的那一张，因此**不会触发截图，也不会和脚本
    争抢模拟器** —— 这是它和 `/tool/annotator` 的实时画面（另建 Device 实例自己
    截图，会抢端口/窗口句柄）的关键区别，两者可以同时使用。

    消息是「json 元信息 + 二进制 JPEG」成对发送的：前端收到二进制帧时，配上最近
    一条元信息就知道这张图是什么时候截的，从而判断画面是否还在更新。画面没变化
    时不重复推送，所以脚本停止后前端会稳定停在最后一帧上，而不是被反复刷屏。

    Args:
        instance: 配置名，与脚本配置（`script.name`）一致。
    """

    try:
        config_name = _normalize_live_instance(instance)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        await websocket.close(code=1008, reason=str(detail.get('code', 'invalid_name')))
        return

    await websocket.accept()
    log_ws_event(f'screenshot_live_ws[{config_name}] connect')

    last_frame_id: str | None = None
    announced_empty = False
    try:
        while True:
            # 同步读取：zerorpc 的 gevent hub 是线程局部的，丢进线程池会让同一个
            # 客户端跨线程使用而报错（详见 _read_live_frame 的说明）。
            frame = _read_live_frame(config_name)
            if frame is None or not frame.get('exists'):
                # 还没跑过脚本，或图像服务不可用。只在第一次告知，避免刷屏。
                if not announced_empty:
                    await websocket.send_json({'event': 'empty'})
                    announced_empty = True
                await asyncio.sleep(LIVE_POLL_INTERVAL)
                continue
            announced_empty = False

            frame_id = frame.get('frame_id')
            if frame_id == last_frame_id:
                # 画面没变（脚本停了，或两帧恰好相同），不必重复推送同一张图。
                await asyncio.sleep(LIVE_POLL_INTERVAL)
                continue

            await websocket.send_json(
                {
                    'event': 'frame',
                    'frame_id': frame_id,
                    'created_at': frame.get('created_at'),
                }
            )
            await websocket.send_bytes(frame['jpeg'])
            last_frame_id = frame_id
            await asyncio.sleep(LIVE_POLL_INTERVAL)
    except WebSocketDisconnect:
        log_ws_event(f'screenshot_live_ws[{config_name}] disconnect')
    except asyncio.CancelledError:
        # 服务端关闭时 uvicorn 会取消这个协程。记一条日志后继续向上抛 ——
        # CancelledError 继承自 BaseException，必须传播取消才能正常生效。
        log_ws_event(f'screenshot_live_ws[{config_name}] cancelled')
        raise
    except Exception as e:
        message = str(e).strip().lower()
        if e.__class__.__name__ == 'ClientDisconnected' or 'disconnected' in message:
            log_ws_event(f'screenshot_live_ws[{config_name}] client_disconnected')
        else:
            log_ws_event(
                f'screenshot_live_ws[{config_name}] error: {type(e).__name__}: {e}',
                level='error',
            )
            logger.exception(f'[screenshot] live ws failed, config={config_name}')
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
    finally:
        if websocket.client_state == WebSocketState.DISCONNECTED:
            log_ws_event(f'screenshot_live_ws[{config_name}] closed')
