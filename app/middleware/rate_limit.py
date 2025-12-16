import time
from typing import Dict
from collections import defaultdict

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    """简单的内存速率限制中间件"""
    
    def __init__(self, app, calls: int = 100, period: int = 60):
        """
        初始化速率限制中间件
        
        Args:
            app: FastAPI应用
            calls: 允许的请求数量
            period: 时间窗口（秒）
        """
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.clients: Dict[str, list] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        # 获取客户端IP地址
        client_ip = self.get_client_ip(request)
        current_time = time.time()
        
        # 清理过期的请求记录
        self.clients[client_ip] = [
            timestamp for timestamp in self.clients[client_ip]
            if current_time - timestamp < self.period
        ]
        
        # 检查是否超过速率限制
        if len(self.clients[client_ip]) >= self.calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {self.calls} requests per {self.period} seconds."
            )
        
        # 记录当前请求
        self.clients[client_ip].append(current_time)
        
        # 继续处理请求
        response = await call_next(request)
        return response
    
    def get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP地址，考虑代理情况"""
        # 检查是否通过代理
        if "x-forwarded-for" in request.headers:
            # 如果有多个代理，取第一个IP
            return request.headers["x-forwarded-for"].split(",")[0].strip()
        
        if "x-real-ip" in request.headers:
            return request.headers["x-real-ip"]
        
        # 如果没有代理，使用直接连接的IP
        return request.client.host if request.client else "unknown"


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """针对认证端点的更严格的速率限制"""
    
    def __init__(self, app, calls: int = 5, period: int = 60):
        """
        初始化认证速率限制中间件
        
        Args:
            app: FastAPI应用
            calls: 允许的请求数量
            period: 时间窗口（秒）
        """
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.clients: Dict[str, list] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        # 只对认证相关的端点进行限制
        if request.url.path not in ["/api/v1/auth/login", "/api/v1/auth/login-json", "/api/v1/auth/register"]:
            return await call_next(request)
        
        # 获取客户端IP地址
        client_ip = self.get_client_ip(request)
        current_time = time.time()
        
        # 清理过期的请求记录
        self.clients[client_ip] = [
            timestamp for timestamp in self.clients[client_ip]
            if current_time - timestamp < self.period
        ]
        
        # 检查是否超过速率限制
        if len(self.clients[client_ip]) >= self.calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"认证请求过于频繁，请稍后再试。最多{self.calls}次请求每{self.period}秒。"
            )
        
        # 记录当前请求
        self.clients[client_ip].append(current_time)
        
        # 继续处理请求
        response = await call_next(request)
        return response
    
    def get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP地址，考虑代理情况"""
        # 检查是否通过代理
        if "x-forwarded-for" in request.headers:
            # 如果有多个代理，取第一个IP
            return request.headers["x-forwarded-for"].split(",")[0].strip()
        
        if "x-real-ip" in request.headers:
            return request.headers["x-real-ip"]
        
        # 如果没有代理，使用直接连接的IP
        return request.client.host if request.client else "unknown"