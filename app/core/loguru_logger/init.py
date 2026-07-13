"""根据 Settings 一键初始化日志。"""

from __future__ import annotations

from datetime import timezone

from loguru import logger as loguru_logger

from .config import configure_logging, resolve_log_config
from .intercept import setup_uvicorn_logging, suppress_library_logging

try:
    # Python 3.9+ 标准库时区支持（跨平台，无需 time.tzset）
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def _apply_timezone_patcher(timezone_name: str) -> None:
    """通过 loguru patcher 把每条日志记录的时间转换为指定时区。

    跨平台方案：使用 zoneinfo（Python 3.9+ 标准库），不依赖 time.tzset()（POSIX 专用，
    Windows 不支持）。仅影响日志展示层；数据库仍以 UTC 存储带时区列。

    Args:
        timezone_name: IANA 时区名（如 "Asia/Shanghai"、"UTC"）。无效则回退到 UTC。
    """
    if ZoneInfo is None:
        return

    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc

    def _timezone_patcher(record):
        record["time"] = record["time"].astimezone(tz)
        return record

    loguru_logger.configure(patcher=_timezone_patcher)


def init_logging(settings) -> None:
    """根据 settings 一键初始化日志（run.py 与应用启动 lifespan 共用）。

    关键：uvicorn 开启 reload 时，server 在**子进程**里重新 import 应用，run.py 的 main()
    不会在该子进程执行——必须在 lifespan 启动时再调用一次，保证子进程也用统一格式，否则会
    回退到 loguru 默认格式。幂等：configure_logging 内部先 remove 再 add。

    Args:
        settings: 应用配置实例（含 LOG_* 字段）。以参数传入，避免本模块反向依赖 config。
    """
    _apply_timezone_patcher(getattr(settings, "TIMEZONE", "UTC"))

    log_config = resolve_log_config(
        profile=settings.LOG_PROFILE,
        level=settings.LOG_LEVEL,
        serialize=settings.LOG_SERIALIZE,
        backtrace=settings.LOG_BACKTRACE,
        enable_console=settings.LOG_ENABLE_CONSOLE,
        enable_file=settings.LOG_ENABLE_FILE,
        enable_error_file=settings.LOG_ENABLE_ERROR_FILE,
        log_dir=settings.LOG_DIR,
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
    )
    configure_logging(**log_config)
    suppress_library_logging()
    setup_uvicorn_logging()
