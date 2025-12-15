"""
标准logging兼容的适配器层
提供与标准库logging完全兼容的接口，同时支持结构化日志功能
"""

import logging
import uuid
from typing import Any, Dict, Optional, Union
from contextvars import ContextVar, copy_context

import structlog


# 上下文变量用于存储请求级别的信息
_logging_context: ContextVar[Dict[str, Any]] = ContextVar('logging_context', default={})


class LoggingAdapter:
    """
    标准logging兼容的适配器
    
    这个类提供与标准库logging.Logger兼容的接口，
    同时内部使用structlog进行结构化日志记录
    """
    
    def __init__(self, name: str, level: Union[int, str] = logging.NOTSET):
        """初始化适配器"""
        self.name = name
        self._structured_logger = structlog.get_logger(name)
        
        # 设置日志级别
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.setLevel(level)
    
    def setLevel(self, level: Union[int, str]) -> None:
        """设置日志级别"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.level = level
    
    def isEnabledFor(self, level: Union[int, str]) -> bool:
        """检查是否启用指定级别的日志"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        return level >= self.level
    
    def _log(self, level: int, msg: str, args, exc_info=None, extra=None, stack_info=False, **kwargs):
        """内部日志记录方法"""
        if not self.isEnabledFor(level):
            return
        
        # 获取当前上下文
        context = _logging_context.get().copy()
        
        # 合并额外信息
        if extra:
            context.update(extra)
        
        # 添加日志级别
        level_name = logging.getLevelName(level)
        
        # 使用结构化日志记录
        log_method = getattr(self._structured_logger, level_name.lower(), self._structured_logger.info)
        log_method(msg, **context, **kwargs)
    
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
        kwargs.setdefault('exc_info', True)
        self.error(msg, *args, **kwargs)
    
    def bind(self, **kwargs) -> 'LoggingAdapter':
        """绑定上下文信息，返回新的适配器实例"""
        # 创建新实例
        new_adapter = LoggingAdapter(self.name, self.level)
        
        # 合并当前上下文和新绑定信息
        current_context = _logging_context.get().copy()
        current_context.update(kwargs)
        
        # 绑定到结构化日志器
        new_adapter._structured_logger = self._structured_logger.bind(**kwargs)
        
        return new_adapter
    
    def unbind(self, *keys) -> 'LoggingAdapter':
        """解绑指定的上下文信息"""
        current_context = _logging_context.get().copy()
        for key in keys:
            current_context.pop(key, None)
        
        # 创建新实例
        new_adapter = LoggingAdapter(self.name, self.level)
        new_adapter._structured_logger = self._structured_logger.bind(**current_context)
        
        return new_adapter
    
    def new(self, **kwargs) -> 'LoggingAdapter':
        """创建全新的适配器实例，不继承当前上下文"""
        new_adapter = LoggingAdapter(self.name, self.level)
        new_adapter._structured_logger = self._structured_logger.bind(**kwargs)
        return new_adapter
    
    def get_context(self) -> Dict[str, Any]:
        """获取当前上下文信息"""
        return _logging_context.get().copy()


# 全局适配器缓存
_adapter_cache: Dict[str, LoggingAdapter] = {}


def get_logger(name: str = None) -> LoggingAdapter:
    """
    获取日志适配器实例
    
    Args:
        name: 日志器名称，默认使用调用模块名
        
    Returns:
        LoggingAdapter实例
    """
    if name is None:
        # 自动获取调用模块名
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'unknown')
    
    # 缓存管理
    if name not in _adapter_cache:
        _adapter_cache[name] = LoggingAdapter(name)
    
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
    
    def bind(self, **kwargs) -> 'LoggingContextManager':
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
    return str(uuid.uuid4()).replace('-', '')


# 兼容标准库logging的模块级别函数
def getLogger(name: str = None) -> LoggingAdapter:
    """兼容标准库logging.getLogger"""
    return get_logger(name)


def basicConfig(**kwargs):
    """兼容标准库logging.basicConfig"""
    # 这里只做基本的兼容，实际配置在structured_logger中处理
    level = kwargs.get('level', logging.INFO)
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    
    # 设置所有已创建适配器的级别
    for adapter in _adapter_cache.values():
        adapter.setLevel(level)
    
    # 如果有新的适配器创建，使用这个级别作为默认
    LoggingAdapter.default_level = level