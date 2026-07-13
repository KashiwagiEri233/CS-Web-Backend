"""请求级日志上下文（ContextVar）与便捷绑定工具。"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any, Dict

# 上下文变量用于存储请求级别的信息
_logging_context: ContextVar[Dict[str, Any]] = ContextVar("logging_context", default={})


def set_logging_context(**kwargs):
    """设置全局日志上下文。

    Args:
        **kwargs: 要设置的上下文键值对。
    """
    current = _logging_context.get().copy()
    current.update(kwargs)
    return _logging_context.set(current)


def reset_logging_context(token) -> None:
    """恢复调用 ``set_logging_context`` 前的上下文。"""
    _logging_context.reset(token)


def clear_logging_context():
    """清空全局日志上下文"""
    _logging_context.set({})


def get_logging_context() -> Dict[str, Any]:
    """获取当前全局日志上下文"""
    return _logging_context.get().copy()


class LoggingContextManager:
    """日志上下文管理器，用于临时设置上下文信息。"""

    def __init__(self, **kwargs):
        """初始化上下文管理器"""
        self.context = kwargs
        self.original_context: Dict[str, Any] = {}

    def __enter__(self):
        """进入上下文"""
        self.original_context = _logging_context.get().copy()
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


def bind_context(**kwargs):
    """创建上下文绑定装饰器"""

    def decorator(func):
        def wrapper(*args, **func_kwargs):
            with LoggingContextManager(**kwargs):
                return func(*args, **func_kwargs)

        return wrapper

    return decorator


def generate_request_id() -> str:
    """生成唯一的请求 ID"""
    return str(uuid.uuid4()).replace("-", "")
