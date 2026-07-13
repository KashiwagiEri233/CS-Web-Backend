"""基于 loguru 的日志系统。

对外保持 ``from app.core.loguru_logger import get_logger, init_logging`` 等导入路径不变；
实现按职责拆到子模块，避免单文件过大。

注意：不在模块级别初始化配置，由应用程序统一配置（run.py / lifespan 调用 init_logging）。
"""

from .adapter import LoguruAdapter, basicConfig, get_logger, getLogger
from .config import LOG_PROFILES, configure_logging, resolve_log_config
from .context import (
    LoggingContextManager,
    bind_context,
    clear_logging_context,
    generate_request_id,
    get_logging_context,
    reset_logging_context,
    set_logging_context,
)
from .init import init_logging
from .intercept import InterceptHandler, setup_uvicorn_logging, suppress_library_logging

__all__ = [
    "LoguruAdapter",
    "LoggingContextManager",
    "LOG_PROFILES",
    "get_logger",
    "getLogger",
    "basicConfig",
    "set_logging_context",
    "clear_logging_context",
    "get_logging_context",
    "reset_logging_context",
    "bind_context",
    "generate_request_id",
    "resolve_log_config",
    "configure_logging",
    "suppress_library_logging",
    "InterceptHandler",
    "setup_uvicorn_logging",
    "init_logging",
]
