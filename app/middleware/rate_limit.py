from typing import List, Optional

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.exceptions import ErrorCode
from app.core.rate_limit import build_limiter


def get_client_ip(request: Request) -> str:
    """获取客户端真实IP地址，考虑代理情况"""
    if "x-forwarded-for" in request.headers:
        return request.headers["x-forwarded-for"].split(",")[0].strip()

    if "x-real-ip" in request.headers:
        return request.headers["x-real-ip"]

    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件

    后端由配置决定：配置 REDIS_URL 则跨实例一致限流（Redis 故障自动降级），
    否则使用进程内内存限流。

    Args:
        app: FastAPI应用
        calls: 允许的请求数量
        period: 时间窗口（秒）
        limit_paths: 仅限制的路径列表（为 None 则限制所有路径）
        error_detail: 超限时的错误提示
    """

    # 限流键命名空间，子类可覆盖以区分不同限流域（如认证端点）
    scope = "global"

    def __init__(
        self,
        app,
        calls: int = 100,
        period: int = 60,
        limit_paths: Optional[List[str]] = None,
        error_detail: Optional[str] = None,
    ):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.limit_paths = limit_paths
        self.error_detail = error_detail or (
            f"Rate limit exceeded. Maximum {calls} requests per {period} seconds."
        )
        self.limiter = build_limiter()

    async def dispatch(self, request: Request, call_next):
        # 如果指定了限制路径，则仅对匹配路径生效
        if self.limit_paths and request.url.path not in self.limit_paths:
            return await call_next(request)

        client_ip = get_client_ip(request)
        key = f"ratelimit:{self.scope}:{client_ip}"

        allowed = await self.limiter.is_allowed(key, self.calls, self.period)
        if not allowed:
            # 直接返回 429。注意：不能在中间件中 raise HTTPException——
            # 它会被最外层 ExceptionHandlerMiddleware 当作未处理异常吞成 500。
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "success": False,
                    "error_code": ErrorCode.RateLimit.RATE_LIMIT_EXCEEDED,
                    "message": self.error_detail,
                    "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
                },
                headers={"Retry-After": str(self.period)},
            )

        return await call_next(request)


class AuthRateLimitMiddleware(RateLimitMiddleware):
    """针对认证端点的更严格的速率限制"""

    scope = "auth"

    AUTH_PATHS = [
        "/api/v1/auth/login",
        "/api/v1/auth/login-json",
        "/api/v1/auth/register",
    ]

    def __init__(self, app, calls: int = 5, period: int = 60):
        super().__init__(
            app,
            calls=calls,
            period=period,
            limit_paths=self.AUTH_PATHS,
            error_detail=f"认证请求过于频繁，请稍后再试。最多{calls}次请求每{period}秒。",
        )
