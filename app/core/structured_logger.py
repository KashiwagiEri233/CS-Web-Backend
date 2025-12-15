"""
结构化日志核心模块
基于structlog构建的高级日志处理器和配置
"""

import asyncio
import json
import logging
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path

import structlog
from structlog.stdlib import LoggerFactory, ProcessorFormatter
from structlog.processors import JSONRenderer, dict_tracebacks, add_log_level

from .logging_adapter import get_logging_context


class CustomJSONRenderer(JSONRenderer):
    """自定义JSON渲染器，支持更多格式和选项"""
    
    def __init__(
        self,
        indent: Optional[int] = None,
        sort_keys: bool = False,
        ensure_ascii: bool = False,
        **dumps_kwargs
    ):
        """初始化自定义JSON渲染器"""
        # 检查新版本structlog是否支持这些参数
        try:
            # 尝试新版本的初始化方式
            super().__init__(
                indent=indent,
                sort_keys=sort_keys,
                ensure_ascii=ensure_ascii,
                **dumps_kwargs
            )
        except TypeError:
            # 如果失败，使用更简单的初始化
            super().__init__()
        
        self._indent = indent
        self._sort_keys = sort_keys
        self._ensure_ascii = ensure_ascii
        self._dumps_kwargs = dumps_kwargs
    
    def __call__(self, logger, method_name: str, event_dict: Dict[str, Any]) -> str:
        """渲染日志事件"""
        # 添加额外的时间戳格式
        if 'timestamp' in event_dict and isinstance(event_dict['timestamp'], time.struct_time):
            event_dict['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%S.%fZ', event_dict['timestamp'])
        
        # 添加进程和线程信息
        if hasattr(logger, '_record'):
            event_dict['process_id'] = logger._record.process
            event_dict['thread_id'] = logger._record.thread
        
        # 使用自己的JSON序列化
        return json.dumps(
            event_dict,
            indent=self._indent,
            sort_keys=self._sort_keys,
            ensure_ascii=self._ensure_ascii,
            **self._dumps_kwargs
        )


class ContextProcessor:
    """上下文处理器，自动添加上下文信息到日志中"""
    
    def __call__(self, logger, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        """处理日志事件，添加上下文信息"""
        # 获取全局上下文
        context = get_logging_context()
        
        # 合并上下文到事件字典
        if context:
            event_dict.update(context)
        
        return event_dict


class SecurityProcessor:
    """安全处理器，过滤敏感信息"""
    
    # 敏感字段名称模式
    SENSITIVE_PATTERNS = [
        'password', 'passwd', 'secret', 'token', 'key', 'auth',
        'credential', 'session', 'cookie', 'authorization'
    ]
    
    def __init__(self, mask_char: str = '*', mask_length: int = 8):
        """初始化安全处理器"""
        self.mask_char = mask_char
        self.mask_length = mask_length
        self.mask_value = mask_char * mask_length
    
    def __call__(self, logger, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        """过滤敏感信息"""
        return self._filter_sensitive_data(event_dict)
    
    def _filter_sensitive_data(self, data: Any, path: str = "") -> Any:
        """递归过滤敏感数据"""
        if isinstance(data, dict):
            return {
                key: self._filter_sensitive_data(
                    value, 
                    f"{path}.{key}" if path else key
                )
                for key, value in data.items()
            }
        elif isinstance(data, (list, tuple)):
            return [
                self._filter_sensitive_data(item, f"{path}[{i}]")
                for i, item in enumerate(data)
            ]
        elif self._is_sensitive_field(path):
            return self.mask_value
        else:
            return data
    
    def _is_sensitive_field(self, field_path: str) -> bool:
        """检查字段路径是否包含敏感信息"""
        field_lower = field_path.lower()
        return any(pattern in field_lower for pattern in self.SENSITIVE_PATTERNS)


class PerformanceProcessor:
    """性能处理器，添加性能相关信息"""
    
    def __init__(self, add_thread_info: bool = False, add_memory_info: bool = False):
        """初始化性能处理器"""
        self.add_thread_info = add_thread_info
        self.add_memory_info = add_memory_info
    
    def __call__(self, logger, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        """添加性能相关信息"""
        # 添加线程信息
        if self.add_thread_info:
            event_dict['thread_name'] = threading.current_thread().name
        
        # 添加内存信息
        if self.add_memory_info:
            try:
                import psutil
                process = psutil.Process()
                memory_info = process.memory_info()
                event_dict['memory_rss'] = memory_info.rss
                event_dict['memory_vms'] = memory_info.vms
            except ImportError:
                pass
            except Exception:
                pass
        
        return event_dict


class ConditionalRenderer:
    """条件渲染器，根据环境或条件选择不同的渲染器"""
    
    def __init__(
        self,
        dev_renderer: Callable,
        prod_renderer: Callable,
        condition_func: Optional[Callable[[], bool]] = None
    ):
        """初始化条件渲染器"""
        self.dev_renderer = dev_renderer
        self.prod_renderer = prod_renderer
        self.condition_func = condition_func
    
    def __call__(self, logger, method_name: str, event_dict: Dict[str, Any]) -> str:
        """根据条件选择渲染器"""
        if self.condition_func and self.condition_func():
            return self.prod_renderer(logger, method_name, event_dict)
        else:
            return self.dev_renderer(logger, method_name, event_dict)


class StructuredLoggerConfig:
    """结构化日志配置类"""
    
    def __init__(
        self,
        level: Union[int, str] = logging.INFO,
        processors: Optional[List[Callable]] = None,
        context_class: type = dict,
        logger_factory: Optional[Callable] = None,
        wrapper_class: type = structlog.stdlib.BoundLogger,
        cache_logger_on_first_use: bool = True
    ):
        """初始化配置"""
        self.level = level
        self.processors = processors or self._default_processors()
        self.context_class = context_class
        self.logger_factory = logger_factory or LoggerFactory()
        self.wrapper_class = wrapper_class
        self.cache_logger_on_first_use = cache_logger_on_first_use
    
    def _default_processors(self) -> List[Callable]:
        """默认处理器链"""
        return [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            ContextProcessor(),  # 添加上下文信息
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            SecurityProcessor(),  # 过滤敏感信息
            PerformanceProcessor(),  # 添加性能信息
            structlog.processors.UnicodeDecoder(),
            CustomJSONRenderer(indent=None, sort_keys=False)  # 自定义JSON渲染
        ]
    
    def configure(self):
        """应用配置到structlog"""
        structlog.configure(
            processors=self.processors,
            context_class=self.context_class,
            logger_factory=self.logger_factory,
            wrapper_class=self.wrapper_class,
            cache_logger_on_first_use=self.cache_logger_on_first_use,
        )
        
        # 设置标准库日志级别
        if isinstance(self.level, str):
            level = getattr(logging, self.level.upper(), logging.INFO)
        else:
            level = self.level
        
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=level,
        )


class AsyncStructuredLogger:
    """异步结构化日志器"""
    
    def __init__(self, logger_name: str = "async_logger"):
        """初始化异步日志器"""
        self.logger_name = logger_name
        self._logger = structlog.get_logger(logger_name)
        self._queue = asyncio.Queue()
        self._worker = None
        self._running = False
    
    async def start(self):
        """启动异步日志处理器"""
        if not self._running:
            self._running = True
            self._worker = asyncio.create_task(self._process_logs())
    
    async def stop(self):
        """停止异步日志处理器"""
        if self._running:
            self._running = False
            await self._queue.put(None)  # 发送停止信号
            await self._worker
    
    async def _process_logs(self):
        """处理日志队列"""
        while self._running:
            try:
                log_entry = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                if log_entry is None:  # 停止信号
                    break
                
                level, msg, kwargs = log_entry
                log_method = getattr(self._logger, level, self._logger.info)
                log_method(msg, **kwargs)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                # 避免日志记录本身出错导致无限循环
                print(f"Error in async logger: {e}")
    
    async def _enqueue_log(self, level: str, msg: str, **kwargs):
        """将日志加入队列"""
        if self._running:
            await self._queue.put((level, msg, kwargs))
    
    async def info(self, msg: str, **kwargs):
        """异步INFO级别日志"""
        await self._enqueue_log("info", msg, **kwargs)
    
    async def debug(self, msg: str, **kwargs):
        """异步DEBUG级别日志"""
        await self._enqueue_log("debug", msg, **kwargs)
    
    async def warning(self, msg: str, **kwargs):
        """异步WARNING级别日志"""
        await self._enqueue_log("warning", msg, **kwargs)
    
    async def error(self, msg: str, **kwargs):
        """异步ERROR级别日志"""
        await self._enqueue_log("error", msg, **kwargs)
    
    async def critical(self, msg: str, **kwargs):
        """异步CRITICAL级别日志"""
        await self._enqueue_log("critical", msg, **kwargs)


# 默认配置实例
default_config = StructuredLoggerConfig()


def configure_structured_logging(config: Optional[StructuredLoggerConfig] = None):
    """配置结构化日志系统"""
    if config is None:
        config = default_config
    config.configure()


def get_async_logger(name: str = "async_logger") -> AsyncStructuredLogger:
    """获取异步日志器实例"""
    return AsyncStructuredLogger(name)