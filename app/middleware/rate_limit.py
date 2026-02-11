import time
from typing import Dict, List, Optional
from collections import defaultdict

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


def get_client_ip(request: Request) -> str:
    """获取客户端真实IP地址，考虑代理情况"""
    if "x-forwarded-for" in request.headers:
        return request.headers["x-forwarded-for"].split(",")[0].strip()

    if "x-real-ip" in request.headers:
        return request.headers["x-real-ip"]

    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """内存速率限制中间件

    Args:
        app: FastAPI应用
        calls: 允许的请求数量
        period: 时间窗口（秒）
        limit_paths: 仅限制的路径列表（为 None 则限制所有路径）
        error_detail: 超限时的错误提示
    """

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
        self.clients: Dict[str, list] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # 如果指定了限制路径，则仅对匹配路径生效
        if self.limit_paths and request.url.path not in self.limit_paths:
            return await call_next(request)

        client_ip = get_client_ip(request)
        current_time = time.time()

        # 清理过期的请求记录
        self.clients[client_ip] = [
            ts for ts in self.clients[client_ip] if current_time - ts < self.period
        ]

        # 检查是否超过速率限制
        if len(self.clients[client_ip]) >= self.calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=self.error_detail,
            )

        # 记录当前请求
        self.clients[client_ip].append(current_time)

        return await call_next(request)


class AuthRateLimitMiddleware(RateLimitMiddleware):
    """针对认证端点的更严格的速率限制"""

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
