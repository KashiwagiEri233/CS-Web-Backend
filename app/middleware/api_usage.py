"""API 调用埋点中间件：把每个请求写入 api_call_logs（内存缓冲 + 周期批量落库）。

- 纯 ASGI 中间件（与 monitoring.py 相同手法，避免 BaseHTTPMiddleware 额外开销）。
- 跳过健康检查 / 文档 / 本统计接口自身，避免自指噪声。
- 请求路径只做一次 O(1) 的内存 append，**不再每请求开一个 DB 会话 + commit**
  （写放大治理，与 app/services/view_count.py 的批量落库同一思路）；后台任务按固定
  周期把缓冲批量 INSERT。
- 有界缓冲：DB 长时间不可用时丢弃最旧记录（埋点是观测性数据，绝不拖垮主流程，
  也绝不无限占用内存）；写入失败静默。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Awaitable, Callable, MutableMapping, Optional, Tuple

from app.core.constants import (
    API_USAGE_BUFFER_MAX,
    API_USAGE_FLUSH_BATCH_SIZE,
    API_USAGE_FLUSH_INTERVAL_SECONDS,
)
from app.core.lifecycle import register_shutdown, register_startup
from app.core.loguru_logger import get_logger

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

SILENT_PREFIXES = (
    "/health",
    "/readyz",
    "/docs",
    "/openapi.json",
    "/workbench/stats/api-usage",  # 自身
)

# 缓冲条目：(endpoint, method, status, latency_ms)
_Record = Tuple[str, str, int, int]

_buffer: "deque[_Record]" = deque(maxlen=API_USAGE_BUFFER_MAX)
_stop = asyncio.Event()
_flush_task: Optional[asyncio.Task] = None

logger = get_logger("middleware.api_usage")


class ApiUsageMiddleware:
    """记录每个 API 请求的 endpoint / 状态 / 延迟，内存缓冲后批量落库。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path.startswith(SILENT_PREFIXES):
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", ""))
        start = time.time()
        status = 200

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 200))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            latency_ms = int((time.time() - start) * 1000)
            # O(1) 入缓冲，由后台任务批量落库（满员自动丢弃最旧记录）
            _buffer.append((self._endpoint_of(path), method, status, latency_ms))

    @staticmethod
    def _endpoint_of(path: str) -> str:
        """把 /api/v1/tools/exam/123 归一化为 /api/v1/tools/exam/{id}，避免统计爆炸。"""
        if path.startswith("/api/v1/"):
            parts = path.split("/")
            # 简单启发式：数字段视为 id
            normalized = ["{id}" if p.isdigit() else p for p in parts]
            return "/".join(normalized)
        return path


async def _flush_once() -> int:
    """把缓冲中的一批记录批量写入 api_call_logs（单会话单次 commit）。"""
    if not _buffer:
        return 0

    batch: list[_Record] = []
    while _buffer and len(batch) < API_USAGE_FLUSH_BATCH_SIZE:
        batch.append(_buffer.popleft())

    try:
        # 延迟 import，避免 middleware → database/models 的导入期循环
        from app.database import AsyncSessionLocal
        from app.models.api_usage import ApiCallLog

        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    ApiCallLog(
                        user_id=None,
                        endpoint=endpoint,
                        method=method,
                        status=status,
                        latency_ms=latency_ms,
                    )
                    for endpoint, method, status, latency_ms in batch
                ]
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - 埋点失败绝不抛出
        logger.debug("api usage batch write failed", size=len(batch))
        return 0
    return len(batch)


async def _flush_loop(interval: float) -> None:
    logger.info(f"API 调用埋点落库任务已启动，间隔 {interval}s")
    while not _stop.is_set():
        try:
            n = await _flush_once()
            if n:
                logger.debug(f"API 调用埋点落库 {n} 条")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"API 调用埋点落库失败（已忽略）: {type(e).__name__}: {e}")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("API 调用埋点落库任务已停止")


@register_startup("api_usage_flush", priority=43, critical=False)
async def startup_api_usage_flush() -> None:
    """启动后台批量落库任务（间隔 <=0 则禁用，退化为不落库）。"""
    global _flush_task
    interval = float(API_USAGE_FLUSH_INTERVAL_SECONDS)
    if interval <= 0:
        logger.info("API 调用埋点落库已禁用")
        return
    _stop.clear()
    _flush_task = asyncio.create_task(_flush_loop(interval))


@register_shutdown("api_usage_flush", priority=29)
async def shutdown_api_usage_flush() -> None:
    """停止后台任务并尽力刷出剩余缓冲。"""
    global _flush_task
    _stop.set()
    if _flush_task is not None:
        try:
            await asyncio.wait_for(_flush_task, timeout=5)
        except Exception:  # noqa: BLE001
            _flush_task.cancel()
        _flush_task = None
    try:
        while _buffer:
            if not await _flush_once():
                break
    except Exception:  # noqa: BLE001 - 关闭阶段一律吞错
        pass
