import asyncio
import time
from collections import Counter
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.loguru_logger import get_logger


class LoggingMiddleware(BaseHTTPMiddleware):
    """日志记录中间件"""

    def __init__(self, app):
        super().__init__(app)
        self.logger = get_logger("middleware.logging")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 记录请求开始时间
        request.state.start_time = time.time()

        try:
            self.logger.info(
                "Request started",
                method=request.method,
                url=str(request.url),
                client_ip=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("user-agent", ""),
            )

            response = await call_next(request)

            process_time = time.time() - request.state.start_time
            response.headers["X-Process-Time"] = str(process_time)

            self.logger.info(
                "Request completed",
                method=request.method,
                url=str(request.url),
                status_code=response.status_code,
                process_time_ms=process_time * 1000,
            )

            return response
        except Exception as exc:
            self.logger.error(
                "Request failed",
                method=request.method,
                url=str(request.url),
                error=str(exc),
                exc_info=True,
            )
            raise


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全头中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """性能指标中间件。

    使用 Counter + asyncio.Lock 保证并发下的计数一致性。asyncio 单线程模型下
    Counter 本身已足够安全，Lock 主要为"读总响应时间 + 算平均 + 写回"这种
    复合操作提供原子性，并防止 get_metrics 读到半更新状态。
    """

    # by_path 维度容量上限，防止路由数无限膨胀。实际路由是有限集合，
    # 超过阈值说明 path 混入了参数化高频变体（如把 id 拼进 path），应由调用方治理。
    _MAX_PATH_ENTRIES = 1024

    def __init__(self, app):
        super().__init__(app)
        self._start_time = time.time()
        self._lock = asyncio.Lock()
        self._total_requests = 0
        self._total_errors = 0
        self._total_response_time = 0.0
        self._by_status: Counter = Counter()
        self._by_method: Counter = Counter()
        self._by_path: Counter = Counter()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        method = request.method
        path = request.url.path

        async with self._lock:
            self._total_requests += 1
            self._by_method[method] += 1
            if len(self._by_path) < self._MAX_PATH_ENTRIES or path in self._by_path:
                self._by_path[path] += 1

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            async with self._lock:
                self._total_response_time += process_time
                self._by_status[str(response.status_code)] += 1
                if response.status_code >= 500:
                    self._total_errors += 1

            response.headers["X-Request-Count"] = str(self._total_requests)
            return response
        except Exception:
            async with self._lock:
                self._total_errors += 1
            raise

    def get_metrics(self) -> dict:
        """获取性能指标快照。"""
        total = self._total_requests
        avg_response_time = (
            self._total_response_time / total if total > 0 else 0.0
        )
        error_rate = self._total_errors / total if total > 0 else 0.0
        uptime = time.time() - self._start_time

        return {
            "requests": {
                "total": total,
                "errors": self._total_errors,
                "by_status": dict(self._by_status),
                "by_method": dict(self._by_method),
                "by_path": dict(self._by_path),
            },
            "performance": {
                "avg_response_time": avg_response_time,
                "total_response_time": self._total_response_time,
            },
            "error_rate": error_rate,
            "uptime_seconds": uptime,
        }
