"""限流中间件（纯 ASGI）。

与 monitoring 里的中间件同理，不用 ``BaseHTTPMiddleware``：限流只需要读 scope 里的
path 和对端地址，走原生 ASGI 协议即可，省掉每请求一个 anyio task group 的开销。
"""

from typing import Any, Awaitable, Callable, List, MutableMapping, Optional

from fastapi import status
from fastapi.responses import JSONResponse

from app.core.exceptions import ErrorCode
from app.core.config import settings
from app.core.rate_limit import build_limiter
from app.core.request_context import get_client_ip_from_scope

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


class RateLimitMiddleware:
    """速率限制中间件

    后端由配置决定：配置 REDIS_URL 则跨实例一致限流（Redis 故障自动降级），
    否则使用进程内内存限流。

    Args:
        app: 下游 ASGI 应用
        calls: 允许的请求数量
        period: 时间窗口（秒）
        limit_paths: 仅限制的路径列表（为 None 则限制所有路径）
        exclude_paths: 豁免路径
        error_detail: 超限时的错误提示
    """

    # 限流键命名空间，子类可覆盖以区分不同限流域（如认证端点）
    scope_name = "global"
    DEFAULT_EXCLUDE_PATHS = frozenset({"/health", "/readyz"})

    def __init__(
        self,
        app,
        calls: int = 100,
        period: int = 60,
        limit_paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        error_detail: Optional[str] = None,
    ):
        self.app = app
        self.calls = calls
        self.period = period
        # 命中判断在每个请求上执行，预先转成 set/frozenset 而非逐次线性扫描
        self.limit_paths = frozenset(limit_paths) if limit_paths else None
        self.exclude_paths = frozenset(exclude_paths or self.DEFAULT_EXCLUDE_PATHS)
        self.error_detail = error_detail or (
            f"Rate limit exceeded. Maximum {calls} requests per {period} seconds."
        )
        self.limiter = build_limiter()
        self.trusted_proxies = settings.trusted_proxy_networks

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path in self.exclude_paths:
            await self.app(scope, receive, send)
            return

        # 如果指定了限制路径，则仅对匹配路径生效
        if self.limit_paths is not None and path not in self.limit_paths:
            await self.app(scope, receive, send)
            return

        client_ip = get_client_ip_from_scope(scope, self.trusted_proxies)
        key = f"ratelimit:{self.scope_name}:{client_ip}"

        if not await self.limiter.is_allowed(key, self.calls, self.period):
            # 直接返回 429。注意：不能在中间件中 raise HTTPException——
            # 它会被最外层 ExceptionHandlerMiddleware 当作未处理异常吞成 500。
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "success": False,
                    "errorCode": ErrorCode.RateLimit.RATE_LIMIT_EXCEEDED,
                    "message": self.error_detail,
                    "statusCode": status.HTTP_429_TOO_MANY_REQUESTS,
                },
                headers={"Retry-After": str(self.period)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class AuthRateLimitMiddleware(RateLimitMiddleware):
    """针对认证端点的更严格的速率限制"""

    scope_name = "auth"

    AUTH_PATHS = [
        f"{settings.API_V1_STR}/auth/login",
        f"{settings.API_V1_STR}/auth/login-json",
        f"{settings.API_V1_STR}/auth/register",
        f"{settings.API_V1_STR}/auth/refresh",
    ]

    def __init__(self, app, calls: int = 5, period: int = 60):
        super().__init__(
            app,
            calls=calls,
            period=period,
            limit_paths=self.AUTH_PATHS,
            error_detail=f"认证请求过于频繁，请稍后再试。最多{calls}次请求每{period}秒。",
        )
