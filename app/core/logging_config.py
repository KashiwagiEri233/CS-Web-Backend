"""
应用日志配置
"""
import logging
import logging.config
import sys
import os
from pathlib import Path
from typing import Dict, Any

# 自定义统一格式化器
class UnifiedFormatter(logging.Formatter):
    """
    统一日志格式化器
    格式: 2025-12-15 16:57:01 | INFO | module - message
    """
    
    def __init__(self):
        super().__init__()
        self.default_format = "%(asctime)s | %(levelname)-8s | %(name)s - %(message)s"
        self.default_time_format = "%Y-%m-%d %H:%M:%S"
    
    def format(self, record):
        # 确保模块名不包含完整路径
        module_name = record.name
        if module_name.startswith("app."):
            module_name = module_name[4:]  # 移除 app. 前缀
        
        # 格式化日志级别
        level = record.levelname
        
        # 格式化时间
        formatted_time = self.formatTime(record, self.default_time_format)
        
        # 组合最终消息
        return f"{formatted_time} | {level} | {module_name} - {record.getMessage()}"

# 日志配置
LOG_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "unified": {
            "()": "logging.Formatter",
            "format": "%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "file": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "formatter": "unified",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "formatter": "file",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/app.log",
            "maxBytes": 10485760,  # 10 MB
            "backupCount": 5,
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "sqlalchemy.engine": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "sqlalchemy.pool": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "app": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}


def configure_logging(
    level: str = "INFO",
    enable_console: bool = True,
    enable_file: bool = True,
    enable_performance: bool = False,
    log_dir: str = "logs"
) -> None:
    """
    配置应用日志系统
    
    Args:
        level: 日志级别
        enable_console: 是否启用控制台日志
        enable_file: 是否启用文件日志
        enable_performance: 是否启用性能日志
        log_dir: 日志目录
    """
    # 确保日志目录存在
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # 更新日志配置
    LOG_CONFIG["handlers"]["file"]["filename"] = os.path.join(log_dir, "app.log")
    
    # 根据参数调整配置
    if not enable_console:
        # 禁用控制台日志处理器
        for logger_config in LOG_CONFIG["loggers"].values():
            if "console" in logger_config["handlers"]:
                logger_config["handlers"].remove("console")
        
        if "console" in LOG_CONFIG["root"]["handlers"]:
            LOG_CONFIG["root"]["handlers"].remove("console")
    
    if not enable_file:
        # 禁用文件日志处理器
        for logger_config in LOG_CONFIG["loggers"].values():
            if "file" in logger_config["handlers"]:
                logger_config["handlers"].remove("file")
        
        if "file" in LOG_CONFIG["root"]["handlers"]:
            LOG_CONFIG["root"]["handlers"].remove("file")
    
    # 应用日志配置
    logging.config.dictConfig(LOG_CONFIG)


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        标准日志记录器
    """
    return logging.getLogger(name)


async def start_logging_system() -> None:
    """
    启动日志系统异步组件
    """
    # 这里可以添加异步日志组件的初始化代码
    pass


async def stop_logging_system() -> None:
    """
    停止日志系统异步组件
    """
    # 这里可以添加异步日志组件的清理代码
    pass