"""
控制台输出处理器
支持彩色输出和多种格式
"""

import logging
import sys
from typing import Dict, Optional, Union

try:
    from colorama import Fore, Back, Style, init
    init(autoreset=True)
    COLORS_AVAILABLE = True
except ImportError:
    # 如果没有colorama，定义空的替代品
    class DummyColor:
        def __getattr__(self, name):
            return ""
    
    class DummyStyle:
        def __getattr__(self, name):
            return ""
    
    Fore = DummyColor()
    Back = DummyColor()
    Style = DummyStyle()
    COLORS_AVAILABLE = False


class ColoredConsoleFormatter(logging.Formatter):
    """彩色控制台格式化器"""
    
    # 日志级别颜色映射
    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Back.WHITE,
    }
    
    def __init__(
        self,
        use_colors: bool = True,
        show_level: bool = True,
        show_name: bool = True,
        show_thread: bool = False,
        show_process: bool = False,
        **kwargs
    ):
        """初始化彩色控制台格式化器"""
        super().__init__(**kwargs)
        self.use_colors = use_colors and COLORS_AVAILABLE
        self.show_level = show_level
        self.show_name = show_name
        self.show_thread = show_thread
        self.show_process = show_process
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录"""
        original = super().format(record)
        
        if not self.use_colors:
            return original
        
        # 添加颜色到日志级别
        level_color = self.LEVEL_COLORS.get(record.levelno, "")
        reset = Style.RESET_ALL
        
        # 构建前缀
        parts = []
        
        if self.show_level:
            parts.append(f"{level_color}[{record.levelname}]{reset}")
        
        if self.show_name:
            parts.append(f"{Fore.BLUE}[{record.name}]{reset}")
        
        if self.show_thread:
            parts.append(f"{Fore.MAGENTA}[{record.threadName}]{reset}")
        
        if self.show_process:
            parts.append(f"{Fore.MAGENTA}[{record.process}]{reset}")
        
        # 时间戳
        if hasattr(record, 'asctime'):
            parts.append(f"{Fore.CYAN}[{record.asctime}]{reset}")
        
        prefix = " ".join(parts)
        
        if prefix:
            return f"{prefix} {original}"
        return original


class SimpleConsoleFormatter(logging.Formatter):
    """简单控制台格式化器"""
    
    def __init__(self, prefix: str = "", **kwargs):
        """初始化简单格式化器"""
        super().__init__(**kwargs)
        self.prefix = prefix
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录"""
        formatted = super().format(record)
        if self.prefix:
            return f"{self.prefix}{formatted}"
        return formatted


class ConsoleHandler(logging.Handler):
    """控制台输出处理器"""
    
    def __init__(
        self,
        stream=None,
        use_colors: bool = True,
        use_simple_formatter: bool = False,
        **formatter_kwargs
    ):
        """初始化控制台处理器"""
        super().__init__()
        self.stream = stream or sys.stdout
        
        # 选择格式化器
        if use_simple_formatter:
            formatter = SimpleConsoleFormatter(**formatter_kwargs)
        else:
            formatter = ColoredConsoleFormatter(
                use_colors=use_colors,
                **formatter_kwargs
            )
        
        self.setFormatter(formatter)
    
    def emit(self, record: logging.LogRecord) -> None:
        """发送日志记录到控制台"""
        try:
            msg = self.format(record)
            self.stream.write(msg + '\n')
            self.stream.flush()
        except Exception:
            self.handleError(record)


class StructuredConsoleHandler(ConsoleHandler):
    """结构化日志控制台处理器"""
    
    def __init__(
        self,
        stream=None,
        pretty_print: bool = True,
        **kwargs
    ):
        """初始化结构化控制台处理器"""
        super().__init__(stream, **kwargs)
        self.pretty_print = pretty_print
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化结构化日志"""
        if hasattr(record, 'msg') and isinstance(record.msg, dict):
            # 如果是字典消息，使用JSON格式
            try:
                import json
                if self.pretty_print:
                    formatted = json.dumps(record.msg, indent=2, ensure_ascii=False)
                    return f"\n{formatted}"
                else:
                    formatted = json.dumps(record.msg, ensure_ascii=False)
                    return formatted
            except (TypeError, ValueError):
                pass
        
        return super().format(record)


class MultiOutputConsoleHandler:
    """多输出控制台处理器，支持同时输出到多个流"""
    
    def __init__(self, streams: Optional[list] = None, formatters: Optional[list] = None):
        """初始化多输出处理器"""
        self.streams = streams or [sys.stdout, sys.stderr]
        self.handlers = []
        
        # 为每个流创建处理器
        for i, stream in enumerate(self.streams):
            handler = logging.StreamHandler(stream)
            
            # 为每个处理器设置格式化器
            if formatters and i < len(formatters):
                handler.setFormatter(formatters[i])
            else:
                # 默认格式化器
                if stream == sys.stderr:
                    # 错误流使用红色
                    formatter = ColoredConsoleFormatter(use_colors=True)
                else:
                    # 标准输出使用默认格式
                    formatter = ColoredConsoleFormatter(use_colors=True)
                handler.setFormatter(formatter)
            
            self.handlers.append(handler)
    
    def add_stream(self, stream, formatter: Optional[logging.Formatter] = None) -> None:
        """添加输出流"""
        handler = logging.StreamHandler(stream)
        if formatter:
            handler.setFormatter(formatter)
        self.handlers.append(handler)
    
    def set_level(self, level: Union[int, str]) -> None:
        """设置所有处理器的级别"""
        for handler in self.handlers:
            handler.setLevel(level)
    
    def emit(self, record: logging.LogRecord) -> None:
        """发送记录到所有流"""
        for handler in self.handlers:
            try:
                handler.emit(record)
            except Exception:
                pass  # 忽略单个处理器的错误


def create_colored_console_handler(
    level: Union[int, str] = logging.INFO,
    use_colors: bool = True,
    show_details: bool = False,
    pretty_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
) -> ConsoleHandler:
    """创建彩色控制台处理器的便捷函数"""
    handler = ConsoleHandler(
        use_colors=use_colors,
        use_simple_formatter=not show_details
    )
    
    if show_details:
        handler.setFormatter(
            logging.Formatter(
                pretty_format,
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        )
    
    handler.setLevel(level)
    return handler


def create_simple_console_handler(
    level: Union[int, str] = logging.INFO,
    prefix: str = "[LOG] "
) -> ConsoleHandler:
    """创建简单控制台处理器的便捷函数"""
    formatter = SimpleConsoleFormatter(prefix=prefix)
    handler = ConsoleHandler(use_simple_formatter=True)
    handler.setFormatter(formatter)
    handler.setLevel(level)
    return handler