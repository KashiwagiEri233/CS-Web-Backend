"""
基于loguru的日志系统实现
提供与标准库logging兼容的接口，同时使用loguru作为底层日志处理
"""

import json
import logging
import sys
import uuid
import threading
from datetime import datetime
from typing import Any, Dict, Optional, Union
from pathlib import Path
from contextvars import ContextVar

from loguru import logger as loguru_logger

loguru_logger.level("TRACE", color="<blue>")
loguru_logger.level("DEBUG", color="<cyan>")
loguru_logger.level("INFO", color="<green>")
loguru_logger.level("WARNING", color="<yellow>")
loguru_logger.level("ERROR", color="<red>")
loguru_logger.level("CRITICAL", color="<red><bold>")


_DISPLAY_KEY_MAP: Dict[str, str] = {
    "type": "数据库类型",
    "version": "版本",
    "tables_found": "已找到表数量",
    "total_checked": "检查表总数",
    "table_list": "表列表",
    "method": "请求方法",
    "url": "请求URL",
    "status_code": "响应状态码",
    "process_time": "处理时间",
    "client_ip": "客户端IP",
    "user_agent": "用户代理",
    "error_type": "错误类型",
    "error_message": "错误消息",
    "traceback_id": "追踪ID",
    "request_id": "请求ID",
    "context": "上下文",
}


class _DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


# 上下文变量用于存储请求级别的信息
_logging_context: ContextVar[Dict[str, Any]] = ContextVar("logging_context", default={})


class LoguruAdapter:
    """
    Loguru适配器，提供与标准库logging.Logger兼容的接口
    """

    def __init__(self, name: str, level: Union[int, str] = logging.INFO):
        """初始化适配器"""
        self.name = name
        self._logger = loguru_logger.bind(name=name)

        # 仅记录级别用于 isEnabledFor 判断，不触碰全局 handler 配置
        # handler 的添加由 configure_logging 统一管理，避免每次 get_logger 重置全局
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.level = level

    def setLevel(self, level: Union[int, str]) -> None:
        """设置该适配器的日志级别（仅影响本实例的 isEnabledFor 判断）"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.level = level

    def _map_logging_level_to_loguru(self, level: int) -> str:
        """将logging级别映射到loguru级别"""
        if level >= logging.CRITICAL:
            return "CRITICAL"
        elif level >= logging.ERROR:
            return "ERROR"
        elif level >= logging.WARNING:
            return "WARNING"
        elif level >= logging.INFO:
            return "INFO"
        else:
            return "DEBUG"

    def isEnabledFor(self, level: Union[int, str]) -> bool:
        """检查是否启用指定级别的日志"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        return level >= self.level

    def _log(
        self,
        level: int,
        msg: str,
        args,
        exc_info=None,
        extra=None,
        stack_info=False,
        **kwargs,
    ):
        """内部日志记录方法"""
        if not self.isEnabledFor(level):
            return

        # 添加日志级别名称
        level_name = logging.getLevelName(level)

        # 使用loguru记录日志
        log_method = getattr(self._logger, level_name.lower(), self._logger.info)

        # 格式化参数信息
        if kwargs:
            # 创建格式化的参数字符串
            formatted_params = []
            for k, v in kwargs.items():
                if k == "name":
                    continue

                display_key = _DISPLAY_KEY_MAP.get(k, k)

                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False, cls=_DateTimeEncoder)

                formatted_params.append(f" [{display_key}]: {v}")

            # 将格式化的参数添加到消息中
            if formatted_params:
                msg = f"{msg}" + "".join(formatted_params)

        # 使用 log_method 记录日志，避免将 kwargs 作为格式化参数
        # 这样可以防止 KeyError 错误
        if exc_info:
            log_method(msg, exc_info=exc_info)
        else:
            log_method(msg)

    def debug(self, msg: str, *args, **kwargs):
        """记录DEBUG级别日志"""
        self._log(logging.DEBUG, msg, args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """记录INFO级别日志"""
        self._log(logging.INFO, msg, args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """记录WARNING级别日志"""
        self._log(logging.WARNING, msg, args, **kwargs)

    def warn(self, msg: str, *args, **kwargs):
        """warning的别名"""
        self.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """记录ERROR级别日志"""
        self._log(logging.ERROR, msg, args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """记录CRITICAL级别日志"""
        self._log(logging.CRITICAL, msg, args, **kwargs)

    def fatal(self, msg: str, *args, **kwargs):
        """critical的别名"""
        self.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """记录异常信息，自动添加异常信息"""
        kwargs.setdefault("exc_info", True)
        self.error(msg, *args, **kwargs)

    def bind(self, **kwargs) -> "LoguruAdapter":
        """绑定上下文信息，返回新的适配器实例"""
        # 创建新实例
        new_adapter = LoguruAdapter(self.name, self.level)

        # 绑定到loguru日志器
        new_adapter._logger = self._logger.bind(**kwargs)

        return new_adapter

    def unbind(self, *keys) -> "LoguruAdapter":
        """解绑指定的上下文信息"""
        # 创建新实例
        new_adapter = LoguruAdapter(self.name, self.level)

        # 获取当前绑定信息
        # 注意：loguru没有直接的unbind方法，我们只能重新创建
        return new_adapter

    def new(self, **kwargs) -> "LoguruAdapter":
        """创建全新的适配器实例，不继承当前上下文"""
        new_adapter = LoguruAdapter(self.name, self.level)
        new_adapter._logger = self._logger.bind(**kwargs)
        return new_adapter

    def get_context(self) -> Dict[str, Any]:
        """获取当前上下文信息"""
        return _logging_context.get().copy()

    def addHandler(self, hdlr):
        """添加处理器（兼容性方法）"""
        # loguru使用不同的处理器系统，这里只做兼容性处理
        pass

    def removeHandler(self, hdlr):
        """移除处理器（兼容性方法）"""
        # loguru使用不同的处理器系统，这里只做兼容性处理
        pass


# 全局适配器缓存
_adapter_cache: Dict[str, LoguruAdapter] = {}


def get_logger(name: str = None) -> LoguruAdapter:
    """
    获取日志适配器实例

    Args:
        name: 日志器名称，默认使用调用模块名

    Returns:
        LoguruAdapter实例
    """
    if name is None:
        # 自动获取调用模块名
        import inspect

        frame = inspect.currentframe().f_back
        name = frame.f_globals.get("__name__", "unknown")

    # 缓存管理
    if name not in _adapter_cache:
        _adapter_cache[name] = LoguruAdapter(name)

    return _adapter_cache[name]


def set_logging_context(**kwargs):
    """
    设置全局日志上下文

    Args:
        **kwargs: 要设置的上下文键值对
    """
    current = _logging_context.get().copy()
    current.update(kwargs)
    _logging_context.set(current)


def clear_logging_context():
    """清空全局日志上下文"""
    _logging_context.set({})


def get_logging_context() -> Dict[str, Any]:
    """获取当前全局日志上下文"""
    return _logging_context.get().copy()


class LoggingContextManager:
    """日志上下文管理器，用于临时设置上下文信息"""

    def __init__(self, **kwargs):
        """初始化上下文管理器"""
        self.context = kwargs
        self.original_context = None

    def __enter__(self):
        """进入上下文"""
        self.original_context = _logging_context.get().copy()
        # 合并新上下文
        new_context = self.original_context.copy()
        new_context.update(self.context)
        _logging_context.set(new_context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        _logging_context.set(self.original_context)

    def bind(self, **kwargs) -> "LoggingContextManager":
        """绑定额外的上下文信息"""
        self.context.update(kwargs)
        return self


# 便捷函数
def bind_context(**kwargs):
    """创建上下文绑定装饰器"""

    def decorator(func):
        def wrapper(*args, **func_kwargs):
            with LoggingContextManager(**kwargs):
                return func(*args, **func_kwargs)

        return wrapper

    return decorator


def generate_request_id() -> str:
    """生成唯一的请求ID"""
    return str(uuid.uuid4()).replace("-", "")


# 兼容标准库logging的模块级别函数
def getLogger(name: str = None) -> LoguruAdapter:
    """兼容标准库logging.getLogger"""
    return get_logger(name)


def basicConfig(**kwargs):
    """兼容标准库logging.basicConfig"""
    level = kwargs.get("level", logging.INFO)
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # 设置所有已创建适配器的级别
    for adapter in _adapter_cache.values():
        adapter.setLevel(level)

    # 配置loguru
    loguru_level = LoguruAdapter("", level)._map_logging_level_to_loguru(level)

    # 移除所有现有的处理器
    loguru_logger.remove()

    # 重新添加处理器
    format_str = kwargs.get(
        "format",
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[name]}</cyan> | "
        "\n"
        "<level>→ {message}</level>",
    )

    loguru_logger.add(
        kwargs.get("stream", sys.stdout),
        level=loguru_level,
        format=format_str,
        serialize=kwargs.get("serialize", False),
        colorize=True,  # 启用颜色
        catch=True,  # 捕获异常
    )


# 配置函数
def configure_logging(
    level: Union[int, str] = logging.INFO,
    format_string: Optional[str] = None,
    enable_console: bool = True,
    enable_file: bool = False,
    log_dir: str = "logs",
    app_name: str = "app",
    rotation: str = "10 MB",
    retention: str = "30 days",
    serialize: bool = False,  # 默认不序列化为JSON，以支持彩色输出
    **kwargs,
):
    """
    配置loguru日志系统

    Args:
        level: 日志级别
        format_string: 自定义格式字符串
        enable_console: 是否启用控制台输出
        enable_file: 是否启用文件输出
        log_dir: 日志文件目录
        app_name: 应用名称
        rotation: 日志轮转设置
        retention: 日志保留时间
        serialize: 是否序列化为JSON
        **kwargs: 其他loguru配置参数
    """
    # 移除所有现有的处理器
    loguru_logger.remove()

    # 设置级别
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    loguru_level = LoguruAdapter("", level)._map_logging_level_to_loguru(level)

    # 默认格式 - 更直观的格式，主要信息突出，参数在下方显示
    if format_string is None:
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[name]}</cyan> | "
            "{message}"
        )

    # 添加控制台处理器
    if enable_console:
        loguru_logger.add(
            sys.stdout,
            level=loguru_level,
            format=format_string,
            serialize=serialize,
            colorize=True,  # 启用颜色
            catch=True,  # 捕获异常
            **kwargs,
        )

    # 添加文件处理器
    if enable_file:
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(exist_ok=True)

        log_file = log_dir_path / f"{app_name}.log"

        loguru_logger.add(
            str(log_file),
            level=loguru_level,
            format=format_string,
            rotation=rotation,
            retention=retention,
            serialize=serialize,
            catch=True,  # 捕获异常
            **kwargs,
        )


_LIBRARY_LOGGERS = (
    "uvicorn",
    "uvicorn.access",
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "sqlalchemy.dialects",
    "sqlalchemy.orm",
    "sqlalchemy.compiler",
)

_LIBRARY_LOGGER_LEVELS = {
    "uvicorn.error": logging.ERROR,
}


def suppress_library_logging():
    """统一设置第三方库日志级别，减少噪音输出"""
    for name in _LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for name, level in _LIBRARY_LOGGER_LEVELS.items():
        logging.getLogger(name).setLevel(level)


# 注意：不在模块级别初始化配置，由应用程序统一配置
