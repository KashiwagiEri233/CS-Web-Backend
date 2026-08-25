"""监控 / 日志 / 安全头中间件。

三者都是**纯 ASGI 中间件**（``async def __call__(scope, receive, send)``），
而非 Starlette 的 ``BaseHTTPMiddleware``。原因：BaseHTTPMiddleware 每个请求都要
额外开一个 anyio task group 并用内存对象流转发请求/响应体，本项目一次请求要穿过
5 层中间件，这份固定开销会直接落在 p50 延迟上。这里只需要读 scope、改响应头、
统计耗时，用原生 ASGI 协议实现即可，无需 Request/Response 对象往返。

改响应头的统一手法：包一层 ``send``，拦截 ``http.response.start`` 消息后修改
其 ``headers`` 列表（ASGI 里是 ``list[tuple[bytes, bytes]]``）再转发。
"""

import time
from app.core.constants import SECONDS_PER_YEAR
from collections import Counter
from typing import Any, Awaitable, Callable, MutableMapping, Optional

from starlette.datastructures import Headers

from app.core.loguru_logger import get_logger
from app.core.request_context import get_client_ip_from_scope

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


class LoggingMiddleware:
    """请求日志中间件。

    探针路径（/health、/readyz）默认完全不记日志：k8s 每几秒探一次，prod profile
    下是 JSON 序列化 + 文件轮转，这些噪声既淹没有效日志又白白消耗 IO。
    请求开始记 DEBUG、请求结束记 INFO——正常运行只需要一条「结果」日志，
    开始日志只在排查卡住的请求时才有价值。
    """

    SILENT_PATHS = frozenset({"/health", "/readyz"})

    def __init__(self, app, silent_paths: Optional[frozenset] = None):
        self.app = app
        self.logger = get_logger("middleware.logging")
        self.silent_paths = (
            self.SILENT_PATHS if silent_paths is None else frozenset(silent_paths)
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path in self.silent_paths:
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", ""))
        start_time = time.time()
        # 保留在 scope["state"] 里，供下游（如异常处理器）读取本次请求的起始时间
        scope.setdefault("state", {})
        state = scope["state"]
        if isinstance(state, dict):
            state["start_time"] = start_time

        headers = Headers(scope=scope)
        self.logger.debug(
            "Request started",
            method=method,
            path=path,
            client_ip=get_client_ip_from_scope(scope),
            user_agent=headers.get("user-agent", ""),
        )

        status_code = 500

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                raw = list(message.get("headers") or [])
                process_time = time.time() - start_time
                raw.append((b"x-process-time", f"{process_time}".encode("ascii")))
                message = {**message, "headers": raw}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            self.logger.error(
                "Request failed",
                method=method,
                path=path,
                user_id=_user_id_from_scope(scope),
                error=str(exc),
                exc_info=True,
            )
            raise

        process_time = time.time() - start_time
        self.logger.info(
            "Request completed",
            method=method,
            path=path,
            status_code=status_code,
            process_time_ms=process_time * 1000,
            user_id=_user_id_from_scope(scope),
        )


class SecurityHeadersMiddleware:
    """安全响应头中间件。"""

    # 静态头预先编码成 ASGI 需要的 bytes，避免每个响应重复编码
    _HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"x-xss-protection", b"1; mode=block"),
        # HSTS 无条件下发：应用通常跑在 TLS 终结代理之后，scope["scheme"] 仍是 http
        # （proxy_headers 被刻意关闭），按 scheme 判断反而会在真实生产环境漏发。
        # 浏览器在纯 HTTP 下会忽略该头，无副作用。
        (
            b"strict-transport-security",
            f"max-age={SECONDS_PER_YEAR}; includeSubDomains".encode(),
        ),
        # 纯 JSON API 不需要 CSP，但要避免 URL（可能含资源 id）随跳转泄漏到第三方
        (b"referrer-policy", b"no-referrer"),
    ]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                raw = list(message.get("headers") or [])
                raw.extend(self._HEADERS)
                message = {**message, "headers": raw}
            await send(message)

        await self.app(scope, receive, send_wrapper)


class MetricsMiddleware:
    """性能指标中间件（进程内内存计数）。

    并发安全性：asyncio 是单线程协作式调度，只有在 ``await`` 处才会切换协程。
    下面所有计数更新都是不含 await 的纯同步代码段，因此天然原子——不需要锁。
    （旧实现用 asyncio.Lock 保护这些代码段，每个请求要多两次加解锁，纯属浪费。）
    """

    # by_path 维度容量上限，防止路由数无限膨胀。实际路由是有限集合，
    # 超过阈值说明 path 混入了参数化高频变体（如把 id 拼进 path），应由调用方治理。
    _MAX_PATH_ENTRIES = 1024

    # 当前进程内的实例引用，供 /metrics/json 端点读取指标快照。
    # Starlette 的 app.user_middleware 只存 Middleware 规格（类+参数），不暴露实例，
    # 故在实例化时登记此处，避免端点脆弱地遍历中间件栈。
    _instance: "MetricsMiddleware | None" = None

    def __init__(self, app):
        self.app = app
        MetricsMiddleware._instance = self
        self._start_time = time.time()
        self._total_requests = 0
        self._total_errors = 0
        self._total_response_time = 0.0
        self._by_status: Counter = Counter()
        self._by_method: Counter = Counter()
        self._by_path: Counter = Counter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        app_obj = scope.get("app")
        if app_obj is not None:
            # /metrics/json 端点通过 app.state 拿到本实例（见 main.py）
            app_obj.state.metrics_middleware = self

        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        start_time = time.time()

        self._total_requests += 1
        self._by_method[method] += 1
        request_count = self._total_requests

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                self._total_response_time += time.time() - start_time
                self._by_status[str(status_code)] += 1
                if status_code >= 500:
                    self._total_errors += 1
                # 用路由模板（/users/{user_id}）而非原始 path 做维度：含参路径
                # （/users/123）会无限膨胀，撑爆上限后静默丢统计。
                # scope["route"] 由 Starlette 路由器在进入下游后写入，故此处才可读。
                route = scope.get("route")
                dimension = getattr(route, "path", path)
                if (
                    len(self._by_path) < self._MAX_PATH_ENTRIES
                    or dimension in self._by_path
                ):
                    self._by_path[dimension] += 1
                raw = list(message.get("headers") or [])
                raw.append((b"x-request-count", str(request_count).encode("ascii")))
                message = {**message, "headers": raw}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
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


def _user_id_from_scope(scope: Scope) -> Optional[int]:
    """从 scope 状态里取当前用户 id（鉴权依赖写入），未鉴权时为 None。"""
    state = scope.get("state")
    if isinstance(state, dict):
        value = state.get("user_id")
        if isinstance(value, int):
            return value
    return None
