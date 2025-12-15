import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger


class LoggingMiddleware(BaseHTTPMiddleware):
    """日志记录中间件"""
    
    def __init__(self, app):
        super().__init__(app)
        self.logger = get_logger("middleware.logging")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 记录请求开始时间
        request.state.start_time = time.time()
        
        try:
            # 记录请求信息
            self.logger.info(
                "Request started",
                method=request.method,
                url=str(request.url),
                client_ip=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("user-agent", ""),
            )
            
            # 处理请求
            response = await call_next(request)
            
            # 记录请求和响应信息
            process_time = time.time() - request.state.start_time
            response.headers["X-Process-Time"] = str(process_time)
            
            # 记录响应信息
            self.logger.info(
                "Request completed",
                method=request.method,
                url=str(request.url),
                status_code=response.status_code,
                process_time_ms=process_time * 1000,
            )
            
            return response
        except Exception as exc:
            # 记录异常信息
            self.logger.error(
                "Request failed",
                method=request.method,
                url=str(request.url),
                error=str(exc),
                exc_info=True
            )
            raise


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全头中间件"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # 添加安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """性能指标中间件"""
    
    def __init__(self, app):
        super().__init__(app)
        self.start_time = time.time()
        self.request_count = 0
        self.error_count = 0
        self.total_response_time = 0.0
        
        # 更详细的指标结构
        self.requests_by_status = {}
        self.requests_by_method = {}
        self.requests_by_path = {}
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        self.request_count += 1
        
        # 更新方法计数
        method = request.method
        if method not in self.requests_by_method:
            self.requests_by_method[method] = 0
        self.requests_by_method[method] += 1
        
        # 更新路径计数
        path = request.url.path
        if path not in self.requests_by_path:
            self.requests_by_path[path] = 0
        self.requests_by_path[path] += 1
        
        try:
            response = await call_next(request)
            
            # 记录指标
            process_time = time.time() - start_time
            self.total_response_time += process_time
            
            # 更新状态码计数
            status_code = str(response.status_code)
            if status_code not in self.requests_by_status:
                self.requests_by_status[status_code] = 0
            self.requests_by_status[status_code] += 1
            
            # 添加指标到响应头
            response.headers["X-Request-Count"] = str(self.request_count)
            response.headers["X-Avg-Response-Time"] = str(self.total_response_time / self.request_count)
            
            return response
            
        except Exception as exc:
            self.error_count += 1
            raise
    
    def get_metrics(self) -> dict:
        """获取性能指标"""
        avg_response_time = self.total_response_time / self.request_count if self.request_count > 0 else 0
        error_rate = self.error_count / self.request_count if self.request_count > 0 else 0
        uptime = time.time() - self.start_time
        
        return {
            "requests": {
                "total": self.request_count,
                "by_status": self.requests_by_status,
                "by_method": self.requests_by_method,
                "by_path": self.requests_by_path,
                "request_count": self.request_count,  # 兼容旧格式
                "errors": self.error_count,          # 兼容旧格式
                "error_count": self.error_count      # 兼容旧格式
            },
            "performance": {
                "avg_response_time": avg_response_time,
                "total_response_time": self.total_response_time
            },
            "security": {
                "auth_failures": 0  # 占位符，尚未实现
            },
            "uptime_seconds": uptime,
            # 兼容旧格式
            "error_rate": error_rate
        }