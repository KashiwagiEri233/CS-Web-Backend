"""
日志输出处理器模块
支持多种输出目标：控制台、文件、数据库、远程服务等
"""

import os
import logging
from typing import Dict, Optional

from .console import ConsoleHandler
from .file import FileHandler, RotatingFileHandler
from .database import DatabaseHandler

__all__ = [
    "ConsoleHandler",
    "FileHandler", 
    "RotatingFileHandler",
    "DatabaseHandler",
    "create_colored_console_handler",
    "create_simple_console_handler",
    "setup_log_files",
]


def create_colored_console_handler(
    level: int = logging.INFO,
    use_colors: bool = True,
    show_details: bool = False
) -> ConsoleHandler:
    """创建彩色控制台处理器"""
    # ColoredConsoleFormatter 不接受 show_details 参数，我们只传递它接受的参数
    handler = ConsoleHandler(
        use_colors=use_colors
    )
    handler.setLevel(level)
    return handler


def create_simple_console_handler(
    level: int = logging.INFO,
    format_string: Optional[str] = None
) -> ConsoleHandler:
    """创建简单控制台处理器"""
    return ConsoleHandler(
        level=level,
        use_colors=False,
        format_string=format_string or "%(levelname)s: %(message)s"
    )


def setup_log_files(
    log_dir: str = "logs",
    app_name: str = "fastapi_app",
    max_size_mb: int = 10,
    backup_count: int = 5
) -> Dict[str, logging.Handler]:
    """设置日志文件"""
    handlers = {}
    
    # 创建日志目录
    os.makedirs(log_dir, exist_ok=True)
    
    # 应用日志
    app_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, f"{app_name}.log"),
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count
    )
    handlers["app"] = app_handler
    
    # 错误日志
    error_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, f"{app_name}_error.log"),
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count
    )
    error_handler.setLevel(logging.ERROR)
    handlers["error"] = error_handler
    
    # 访问日志
    access_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, f"{app_name}_access.log"),
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count
    )
    handlers["access"] = access_handler
    
    # 安全日志
    security_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, f"{app_name}_security.log"),
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count
    )
    handlers["security"] = security_handler
    
    return handlers