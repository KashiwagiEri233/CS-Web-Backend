import logging
import sys
import time
from typing import Any, Dict

import structlog
from fastapi import Request, Response
from fastapi.logger import logger as fastapi_logger

# 如果pythonjsonlogger不可用，使用标准JSON格式化器
try:
    from pythonjsonlogger import jsonlogger
    JSONFormatter = jsonlogger.JsonFormatter
except ImportError:
    class JSONFormatter(logging.Formatter):
        def format(self, record):
            return f"{record.levelname}: {record.getMessage()}"

# 配置结构化日志
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# 获取结构化日志记录器
logger = structlog.get_logger()

# 配置标准库日志记录器
logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)

# 配置FastAPI日志记录器
fastapi_logger.addHandler(logging.StreamHandler())
fastapi_logger.setLevel(logging.INFO)


def setup_logging():
    """设置应用日志记录"""
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 创建处理器
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    
    # 添加处理器到根日志记录器
    root_logger.addHandler(handler)


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