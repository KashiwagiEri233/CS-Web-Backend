"""
日志中间件
"""
import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# 获取日志记录器
logger = logging.getLogger("middleware")


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # 记录请求开始
        logger.info(f"请求开始: {request.method} {request.url.path}")
        
        # 处理请求
        response = await call_next(request)
        
        # 计算处理时间
        process_time = time.time() - start_time
        
        # 记录响应
        logger.info(f"响应: {response.status_code} - Time: {process_time:.4f}s - URL: {request.url}")
        
        return response


class DatabaseLoggingMiddleware:
    """数据库日志记录器"""
    
    @staticmethod
    def log_connection():
        """记录数据库连接"""
        db_logger = logging.getLogger("database")
        db_logger.debug("从连接池取出连接")
        
        def log_close():
            db_logger.debug("连接返回连接池")
        
        return log_close
    
    @staticmethod
    def log_reset():
        """记录数据库连接重置"""
        db_logger = logging.getLogger("database")
        db_logger.debug("数据库连接已重置")