"""
高级日志系统
兼容标准库logging的结构化日志系统，支持多目标输出、上下文追踪和性能监控
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union

# 导入核心组件
from ..logging_adapter import (
    LoggingAdapter, get_logger, set_logging_context, clear_logging_context,
    get_logging_context, LoggingContextManager, bind_context,
    generate_request_id, getLogger as get_standard_logger, basicConfig
)

from ..structured_logger import (
    StructuredLoggerConfig, configure_structured_logging, AsyncStructuredLogger,
    get_async_logger, default_config
)

from .context import (
    ContextManager, TraceManager, RequestTracker, PerformanceTracker,
    LoggingContextMiddleware, traced_operation, performance_tracked,
    request_context, get_request_id, get_trace_id, get_user_id
)

from .performance import (
    PerformanceMonitor, SlowQueryMonitor, SystemResourceMonitor,
    performance_monitor, slow_query_monitor, resource_monitor,
    monitor_performance, monitor_performance_async, monitor_database_query,
    performance_tracked as perf_tracked, slow_query_tracked,
    setup_performance_monitoring, get_performance_summary
)

from .database_integration import (
    DatabaseConfig, LogEntry, MCPDatabaseLogger, get_database_logger,
    setup_database_logging, stop_database_logging, DatabaseLogHandler
)

# 导入处理器
from .handlers import (
    ConsoleHandler, FileHandler, RotatingFileHandler, DatabaseHandler,
    create_colored_console_handler, create_simple_console_handler,
    setup_log_files
)

# 版本信息
__version__ = "1.0.0"
__all__ = [
    # 核心适配器
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
    
    # 结构化日志
    "StructuredLoggerConfig",
    "configure_structured_logging",
    "AsyncStructuredLogger",
    "get_async_logger",
    "default_config",
    
    # 上下文追踪
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
]


class AdvancedLoggingSystem:
    """高级日志系统主类"""
    
    def __init__(self):
        """初始化日志系统"""
        self._configured = False
        self._db_logger = None
        self._performance_monitors = {}
    
    def configure(
        self,
        level: Union[int, str] = logging.INFO,
        enable_console: bool = True,
        enable_file: bool = False,
        enable_database: bool = False,
        enable_performance: bool = False,
        log_dir: str = "logs",
        app_name: str = "fastapi_app",
        database_config: Optional[DatabaseConfig] = None,
        console_format: str = "colored",
        file_max_size_mb: int = 10,
        file_backup_count: int = 5,
        performance_thresholds: Optional[Dict[str, Dict[str, float]]] = None,
        **kwargs
    ) -> None:
        """配置日志系统"""
        
        # 1. 配置结构化日志
        structlog_config = StructuredLoggerConfig(level=level)
        configure_structured_logging(structlog_config)
        
        # 2. 配置控制台处理器
        if enable_console:
            console_handler = create_colored_console_handler(
                level=level,
                use_colors=(console_format == "colored"),
                show_details=True
            )
            logging.root.addHandler(console_handler)
        
        # 3. 配置文件处理器
        if enable_file:
            file_handlers = setup_log_files(
                log_dir=log_dir,
                app_name=app_name,
                max_size_mb=file_max_size_mb,
                backup_count=file_backup_count
            )
            for handler in file_handlers.values():
                logging.root.addHandler(handler)
        
        # 4. 配置数据库处理器
        if enable_database and database_config:
            async def setup_db():
                await setup_database_logging(
                    host=database_config.host,
                    port=database_config.port,
                    database=database_config.database,
                    username=database_config.username,
                    password=database_config.password,
                    table_name=kwargs.get("database_table", "application_logs")
                )
            
            # 注意：这里需要在异步上下文中调用
            self._db_setup_task = setup_db()
        
        # 5. 配置性能监控
        if enable_performance:
            slow_query_threshold = kwargs.get("slow_query_threshold_ms", 1000.0)
            setup_performance_monitoring(
                enabled=True,
                slow_query_threshold_ms=slow_query_threshold,
                monitor_resources=True
            )
            
            # 设置性能阈值
            if performance_thresholds:
                for operation_name, thresholds in performance_thresholds.items():
                    performance_monitor.set_threshold(
                        operation_name=operation_name,
                        warning_threshold_ms=thresholds.get("warning", 1000.0),
                        error_threshold_ms=thresholds.get("error", 3000.0),
                        sample_rate=thresholds.get("sample_rate", 1.0)
                    )
        
        self._configured = True
    
    async def start_async(self) -> None:
        """启动异步组件"""
        if self._configured:
            # 启动数据库日志记录器
            if hasattr(self, '_db_setup_task'):
                await self._db_setup_task
            
            # 启动性能监控
            if performance_monitor.enabled:
                resource_monitor.start_monitoring()
    
    async def stop_async(self) -> None:
        """停止异步组件"""
        # 停止数据库日志记录器
        await stop_database_logging()
        
        # 停止性能监控
        resource_monitor.stop_monitoring()
    
    def get_logger(self, name: str = None) -> LoggingAdapter:
        """获取日志记录器"""
        return get_logger(name)
    
    def set_context(self, **kwargs) -> None:
        """设置日志上下文"""
        set_logging_context(**kwargs)
    
    def clear_context(self) -> None:
        """清空日志上下文"""
        clear_logging_context()
    
    def with_context(self, **kwargs) -> LoggingContextManager:
        """创建临时上下文管理器"""
        return LoggingContextManager(**kwargs)
    
    def trace_operation(self, operation_name: str = None):
        """创建操作追踪装饰器"""
        return traced_operation(operation_name)
    
    def monitor_performance(self, operation_name: str = None):
        """创建性能监控装饰器"""
        return performance_tracked(operation_name)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        return get_performance_summary()
    
    def add_alert_handler(self, handler: callable) -> None:
        """添加性能告警处理器"""
        performance_monitor.add_alert_handler(handler)
        slow_query_monitor.add_alert_handler(handler)


# 创建全局日志系统实例
logging_system = AdvancedLoggingSystem()


# 便捷函数
def configure_logging(**kwargs) -> None:
    """配置日志系统（便捷函数）"""
    logging_system.configure(**kwargs)


async def start_logging_system() -> None:
    """启动日志系统（便捷函数）"""
    await logging_system.start_async()


async def stop_logging_system() -> None:
    """停止日志系统（便捷函数）"""
    await logging_system.stop_async()


def get_advanced_logger(name: str = None) -> LoggingAdapter:
    """获取高级日志记录器（便捷函数）"""
    return logging_system.get_logger(name)


# 与现有代码集成函数
def integrate_with_fastapi(app, **config):
    """与FastAPI应用集成"""
    # 配置日志系统
    logging_system.configure(**config)
    
    # 添加中间件
    app.add_middleware(LoggingContextMiddleware)
    
    # 返回应用以支持链式调用
    return app


# 导入现有的日志函数以保持兼容性
def log_request_response(request, call_next):
    """兼容现有的请求响应日志函数"""
    # 使用新日志系统实现
    logger = get_logger("middleware.request")
    
    async def middleware_func():
        start_time = time.time()
        logger.info(
            "Request started",
            method=request.method,
            url=str(request.url),
            client_ip=request.client.host if request.client else "unknown",
        )
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        logger.info(
            "Request completed",
            method=request.method,
            url=str(request.url),
            status_code=response.status_code,
            process_time_ms=process_time * 1000,
        )
        
        return response
    
    return middleware_func()


def log_exception(request, exc):
    """兼容现有的异常日志函数"""
    # 使用新日志系统实现
    logger = get_logger("middleware.exception")
    logger.error(
        "Request exception",
        method=getattr(request, 'method', 'unknown'),
        url=getattr(request, 'url', 'unknown'),
        error=str(exc),
        exc_info=True
    )


def log_user_action(user_id: int, action: str, resource: str, details: Dict[str, Any] = None):
    """兼容现有的用户操作日志函数"""
    # 使用新日志系统实现
    logger = get_logger("user_action")
    logger.info(
        "User action",
        user_id=user_id,
        action=action,
        resource=resource,
        details=details or {}
    )


def log_security_event(event_type: str, user_id: int = None, details: Dict[str, Any] = None):
    """兼容现有的安全事件日志函数"""
    # 使用新日志系统实现
    logger = get_logger("security")
    logger.warning(
        "Security event",
        event_type=event_type,
        user_id=user_id,
        details=details or {}
    )


# 添加向后兼容的setup_logging函数
def setup_logging():
    """向后兼容的日志设置函数"""
    configure_logging(
        level="INFO",
        enable_console=True,
        use_colors=True
    )