import asyncio
import time
from collections import Counter
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.loguru_logger import get_logger
from app.core.request_context import get_client_ip


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
                path=request.url.path,
                client_ip=get_client_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )

            response = await call_next(request)

            process_time = time.time() - request.state.start_time
            response.headers["X-Process-Time"] = str(process_time)

            self.logger.info(
                "Request completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                process_time_ms=process_time * 1000,
                user_id=getattr(request.state, "user_id", None),
            )

            return response
        except Exception as exc:
            self.logger.error(
                "Request failed",
                method=request.method,
                path=request.url.path,
                user_id=getattr(request.state, "user_id", None),
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

    # 当前进程内的实例引用，供 /metrics/json 端点读取指标快照。
    # Starlette 的 app.user_middleware 只存 Middleware 规格（类+参数），不暴露实例，
    # 故在实例化时登记此处，避免端点脆弱地遍历中间件栈。
    _instance: "MetricsMiddleware | None" = None

    def __init__(self, app):
        super().__init__(app)
        MetricsMiddleware._instance = self
        self._start_time = time.time()
        # 延迟创建 Lock：Python 3.9 在无 running loop 时 asyncio.Lock() 会
        # RuntimeError；构造常发生在 import / 同步测试中，真正用时（dispatch）必有 loop。
        self._lock: asyncio.Lock | None = None
        self._total_requests = 0
        self._total_errors = 0
        self._total_response_time = 0.0
        self._by_status: Counter = Counter()
        self._by_method: Counter = Counter()
        self._by_path: Counter = Counter()

    def _get_lock(self) -> asyncio.Lock:
        """在已有事件循环的上下文中惰性创建锁。"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request.app.state.metrics_middleware = self
        start_time = time.time()
        method = request.method
        lock = self._get_lock()

        async with lock:
            self._total_requests += 1
            self._by_method[method] += 1

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            # 用路由模板（/users/{user_id}）而非原始 path 做维度：含参路径
            # （/users/123）会无限膨胀，撑爆上限后静默丢统计。
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)

            async with lock:
                self._total_response_time += process_time
                self._by_status[str(response.status_code)] += 1
                if len(self._by_path) < self._MAX_PATH_ENTRIES or path in self._by_path:
                    self._by_path[path] += 1
                if response.status_code >= 500:
                    self._total_errors += 1

            response.headers["X-Request-Count"] = str(self._total_requests)
            return response
        except Exception:
            async with lock:
                self._total_errors += 1
            raise

    def get_metrics(self) -> dict:
        """获取性能指标快照。"""
        total = self._total_requests
        avg_response_time = self._total_response_time / total if total > 0 else 0.0
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
