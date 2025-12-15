"""
基础处理器抽象类
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union


class BaseHandler(ABC):
    """日志处理器基类"""
    
    def __init__(
        self,
        level: Union[int, str] = logging.INFO,
        formatter: Optional[logging.Formatter] = None
    ):
        """初始化基础处理器"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        
        self.level = level
        self.formatter = formatter
        self.enabled = True
    
    def set_level(self, level: Union[int, str]) -> None:
        """设置日志级别"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.level = level
    
    def is_enabled_for(self, level: Union[int, str]) -> bool:
        """检查是否启用指定级别"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        return level >= self.level and self.enabled
    
    def set_formatter(self, formatter: logging.Formatter) -> None:
        """设置格式化器"""
        self.formatter = formatter
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录"""
        if self.formatter:
            return self.formatter.format(record)
        return record.getMessage()
    
    def enable(self) -> None:
        """启用处理器"""
        self.enabled = True
    
    def disable(self) -> None:
        """禁用处理器"""
        self.enabled = False
    
    @abstractmethod
    def emit(self, record: logging.LogRecord) -> None:
        """发送日志记录到指定目标"""
        pass
    
    def handle(self, record: logging.LogRecord) -> bool:
        """处理日志记录"""
        if not self.is_enabled_for(record.levelno):
            return False
        
        try:
            self.emit(record)
            return True
        except Exception:
            self.handleError(record)
            return False
    
    def handleError(self, record: logging.LogRecord) -> None:
        """处理发送错误"""
        logging.raiseExceptions = False  # 避免无限循环


class AsyncBaseHandler(BaseHandler):
    """异步处理器基类"""
    
    def __init__(
        self,
        level: Union[int, str] = logging.INFO,
        formatter: Optional[logging.Formatter] = None,
        buffer_size: int = 100,
        flush_interval: float = 5.0
    ):
        """初始化异步处理器"""
        super().__init__(level, formatter)
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self._buffer = []
        self._last_flush = time.time()
    
    async def async_emit(self, record: logging.LogRecord) -> None:
        """异步发送日志记录"""
        self._buffer.append(record)
        
        # 检查是否需要刷新
        current_time = time.time()
        if (
            len(self._buffer) >= self.buffer_size or
            current_time - self._last_flush >= self.flush_interval
        ):
            await self._flush_buffer()
            self._last_flush = current_time
    
    @abstractmethod
    async def _flush_buffer(self) -> None:
        """刷新缓冲区"""
        pass
    
    def emit(self, record: logging.LogRecord) -> None:
        """同步emit方法（实际上是将记录放入队列）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            asyncio.create_task(self.async_emit(record))
        except RuntimeError:
            # 如果没有事件循环，直接同步处理
            self.sync_emit(record)
    
    def sync_emit(self, record: logging.LogRecord) -> None:
        """同步发送（后备方案）"""
        # 默认实现：直接调用基类的emit
        if hasattr(super(), 'emit'):
            super().emit(record)