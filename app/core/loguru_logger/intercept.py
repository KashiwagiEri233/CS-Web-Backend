"""标准库 logging / uvicorn 输出拦截到 loguru。"""

from __future__ import annotations

import logging
from types import FrameType
from typing import Optional, Union

from loguru import logger as loguru_logger

_LIBRARY_LOGGERS = (
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "sqlalchemy.dialects",
    "sqlalchemy.orm",
    "sqlalchemy.compiler",
)


def suppress_library_logging():
    """统一设置第三方库日志级别，减少噪音输出"""
    for name in _LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


class InterceptHandler(logging.Handler):
    """将标准库 logging 的输出重定向到 loguru，实现统一日志格式。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: Union[str, int] = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame: Optional[FrameType] = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        loguru_logger.opt(depth=depth, exception=record.exc_info).bind(
            name=record.name
        ).log(level, record.getMessage())


def setup_uvicorn_logging() -> None:
    """将 uvicorn / 标准 logging 的输出拦截到 loguru，统一日志格式"""
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = [InterceptHandler()]
        uv_logger.propagate = False
