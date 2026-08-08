"""API 调用埋点中间件：把每个请求写入 api_call_logs（fire-and-forget，不阻塞主流程）。

- 纯 ASGI 中间件（与 monitoring.py 相同手法，避免 BaseHTTPMiddleware 额外开销）。
- 跳过健康检查 / 文档 / 本统计接口自身，避免自指噪声。
- 写入失败静默（观测性不能影响主流程）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, MutableMapping, Optional

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


class ApiUsageMiddleware:
    """记录每个 API 请求的 endpoint / 状态 / 延迟，异步落库。"""

    def __init__(self, app):
        self.app = app
        self.logger = get_logger("middleware.api_usage")

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
            endpoint = self._endpoint_of(path)
            # 异步写库：与响应并行，失败不影响响应
            asyncio.create_task(
                self._log(endpoint=endpoint, method=method, status=status, latency_ms=latency_ms)
            )

    @staticmethod
    def _endpoint_of(path: str) -> str:
        """把 /api/v1/tools/exam/123 归一化为 /api/v1/tools/exam/{id}，避免统计爆炸。"""
        if path.startswith("/api/v1/"):
            parts = path.split("/")
            # 简单启发式：数字段视为 id
            normalized = [
                "{id}" if p.isdigit() else p for p in parts
            ]
            return "/".join(normalized)
        return path

    async def _log(self, endpoint: str, method: str, status: int, latency_ms: int) -> None:
        try:
            from app.database import AsyncSessionLocal
            from app.models.api_usage import ApiCallLog

            async with AsyncSessionLocal() as session:
                session.add(
                    ApiCallLog(
                        user_id=None,
                        endpoint=endpoint,
                        method=method,
                        status=status,
                        latency_ms=latency_ms,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - 埋点失败绝不抛出
            self.logger.debug("api usage log write failed", endpoint=endpoint, status=status)
