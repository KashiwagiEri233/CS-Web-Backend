"""
高级日志系统
兼容标准库logging的结构化日志系统，支持多目标输出、上下文追踪和性能监控
"""

from typing import Any, Dict

# 导入核心组件（从loguru适配器导入，取代废弃的structlog模块）
from ..loguru_logger import (
    LoguruAdapter as LoggingAdapter,
    get_logger,
    set_logging_context,
    clear_logging_context,
    get_logging_context,
    LoggingContextManager,
    bind_context,
    generate_request_id,
    getLogger as get_standard_logger,
    basicConfig,
)

from .context import (
    ContextManager,
    TraceManager,
    RequestTracker,
    PerformanceTracker,
    LoggingContextMiddleware,
    traced_operation,
    performance_tracked,
    request_context,
    get_request_id,
    get_trace_id,
    get_user_id,
)

from .performance import (
    PerformanceMonitor,
    SlowQueryMonitor,
    SystemResourceMonitor,
    performance_monitor,
    slow_query_monitor,
    resource_monitor,
    monitor_performance,
    monitor_performance_async,
    monitor_database_query,
    performance_tracked as perf_tracked,
    slow_query_tracked,
    setup_performance_monitoring,
    get_performance_summary,
)

from .database_integration import (
    DatabaseConfig,
    LogEntry,
    MCPDatabaseLogger,
    get_database_logger,
    setup_database_logging,
    stop_database_logging,
    DatabaseLogHandler,
)

# 导入处理器
from .handlers import (
    ConsoleHandler,
    FileHandler,
    RotatingFileHandler,
    DatabaseHandler,
    create_colored_console_handler,
    create_simple_console_handler,
    setup_log_files,
)

# 版本信息
__version__ = "1.0.0"
__all__ = [
    "LoggingAdapter",
    "get_logger",
    "set_logging_context",
    "clear_logging_context",
    "get_logging_context",
    "LoggingContextManager",
    "bind_context",
    "generate_request_id",
    "get_standard_logger",
    "basicConfig",
    "ContextManager",
    "TraceManager",
    "RequestTracker",
    "PerformanceTracker",
    "LoggingContextMiddleware",
    "traced_operation",
    "performance_tracked",
    "request_context",
    "get_request_id",
    "get_trace_id",
    "get_user_id",
    # 性能监控
    "PerformanceMonitor",
    "SlowQueryMonitor",
    "SystemResourceMonitor",
    "performance_monitor",
    "slow_query_monitor",
    "resource_monitor",
    "monitor_performance",
    "monitor_performance_async",
    "monitor_database_query",
    "perf_tracked",
    "slow_query_tracked",
    "setup_performance_monitoring",
    "get_performance_summary",
    # 数据库集成
    "DatabaseConfig",
    "LogEntry",
    "MCPDatabaseLogger",
    "get_database_logger",
    "setup_database_logging",
    "stop_database_logging",
    "DatabaseLogHandler",
    # 处理器
    "ConsoleHandler",
    "FileHandler",
    "RotatingFileHandler",
    "DatabaseHandler",
    "create_colored_console_handler",
    "create_simple_console_handler",
    "setup_log_files",
    "log_exception",
    "log_user_action",
    "log_security_event",
]


def log_exception(request, exc):
    logger = get_logger("middleware.exception")
    logger.error(
        "Request exception",
        method=getattr(request, "method", "unknown"),
        url=getattr(request, "url", "unknown"),
        error=str(exc),
        exc_info=True,
    )


def log_user_action(
    user_id: int, action: str, resource: str, details: Dict[str, Any] = None
):
    logger = get_logger("user_action")
    logger.info(
        "User action",
        user_id=user_id,
        action=action,
        resource=resource,
        details=details or {},
    )


def log_security_event(
    event_type: str, user_id: int = None, details: Dict[str, Any] = None
):
    logger = get_logger("security")
    logger.warning(
        "Security event", event_type=event_type, user_id=user_id, details=details or {}
    )
