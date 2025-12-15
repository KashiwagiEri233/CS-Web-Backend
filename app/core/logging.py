import sys
import time
import logging
from typing import Any, Dict

from fastapi import Request, Response
from fastapi.logger import logger as fastapi_logger

# 使用loguru作为日志系统
from .loguru_logger import get_logger, configure_logging

# 获取日志记录器
logger = get_logger("app")

# 配置日志系统
configure_logging(
    level="INFO",
    enable_console=True,
    enable_file=True,
    log_dir="logs",
    app_name="fastapi_app",
    serialize=False  # 确保彩色输出
)

# 配置FastAPI日志记录器
fastapi_logger.addHandler(sys.stdout)


def setup_logging():
    """设置应用日志记录"""
    # 使用loguru配置日志系统
    configure_logging(
        level="INFO",
        enable_console=True,
        enable_file=True,
        log_dir="logs",
        app_name="fastapi_app",
        serialize=False  # 确保彩色输出
    )
    
    # 创建处理器
    handler = logging.StreamHandler(sys.stdout)
    # 使用loguru不需要额外的格式化器
    
    # 添加处理器到根日志记录器（如果需要）
    # root_logger.addHandler(handler)


async def log_request_response(request: Request, call_next):
    """记录请求和响应的中间件"""
    start_time = request.state.start_time = time.time()
    
    # 记录请求信息
    logger.info(
        "Request started",
        method=request.method,
        url=str(request.url),
        client_ip=request.client.host,
        user_agent=request.headers.get("user-agent", ""),
    )
    
    # 处理请求
    response = await call_next(request)
    
    # 计算处理时间
    process_time = time.time() - start_time
    
    # 记录响应信息
    logger.info(
        "Request completed",
        method=request.method,
        url=str(request.url),
        status_code=response.status_code,
        process_time=process_time,
    )
    
    # 添加处理时间到响应头
    response.headers["X-Process-Time"] = str(process_time)
    return response


def log_exception(request: Request, exc):
    """记录异常信息"""
    logger.error(
        "Request exception",
        method=request.method,
        url=str(request.url),
        exc_info=exc,
    )


def log_user_action(user_id: int, action: str, resource: str, details: Dict[str, Any] = None):
    """记录用户操作"""
    logger.info(
        "User action",
        user_id=user_id,
        action=action,
        resource=resource,
        details=details or {},
    )


def log_security_event(event_type: str, user_id: int = None, details: Dict[str, Any] = None):
    """记录安全事件"""
    logger.warning(
        "Security event",
        event_type=event_type,
        user_id=user_id,
        details=details or {},
    )