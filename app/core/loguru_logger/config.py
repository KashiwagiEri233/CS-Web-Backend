"""日志 profile 解析与 sink 配置。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

from loguru import logger as loguru_logger

from .adapter import LoguruAdapter, _adapter_cache

# 日志 profile 预置配置
# dev: 开发级（彩色控制台 + DEBUG + 完整回溯栈，无文件）
# prod: 生产级（JSON 序列化 + 文件轮转 + 独立 error 日志 + INFO）
LOG_PROFILES: Dict[str, Dict[str, Any]] = {
    "dev": {
        "level": "DEBUG",
        "serialize": False,
        "backtrace": True,
        "enable_console": True,
        "enable_file": False,
        "enable_error_file": False,
    },
    "prod": {
        "level": "INFO",
        "serialize": True,
        "backtrace": False,
        "enable_console": True,
        "enable_file": True,
        "enable_error_file": True,
    },
}


def resolve_log_config(
    profile: str = "dev",
    level: str = "",
    serialize: Optional[bool] = None,
    backtrace: Optional[bool] = None,
    enable_console: Optional[bool] = None,
    enable_file: Optional[bool] = None,
    enable_error_file: Optional[bool] = None,
    log_dir: str = "logs",
    rotation: str = "10 MB",
    retention: str = "30 days",
    app_name: str = "fastapi_app",
) -> Dict[str, Any]:
    """根据 profile 解析最终日志配置，显式传参覆盖 profile 默认值。

    Args:
        profile: 日志 profile，dev 或 prod。
        level: 日志级别，留空用 profile 默认。
        serialize: 是否 JSON 序列化，None 用 profile 默认。
        backtrace: 是否完整回溯栈，None 用 profile 默认。
        enable_console: 是否控制台输出，None 用 profile 默认。
        enable_file: 是否文件输出，None 用 profile 默认。
        enable_error_file: 是否独立 error 文件，None 用 profile 默认。
        log_dir: 日志目录。
        rotation: 轮转大小。
        retention: 保留时间。
        app_name: 应用名称。

    Returns:
        configure_logging 的完整参数 dict。
    """
    base = LOG_PROFILES.get(profile, LOG_PROFILES["dev"]).copy()

    if level:
        base["level"] = level
    if serialize is not None:
        base["serialize"] = serialize
    if backtrace is not None:
        base["backtrace"] = backtrace
    if enable_console is not None:
        base["enable_console"] = enable_console
    if enable_file is not None:
        base["enable_file"] = enable_file
    if enable_error_file is not None:
        base["enable_error_file"] = enable_error_file

    base["log_dir"] = log_dir
    base["rotation"] = rotation
    base["retention"] = retention
    base["app_name"] = app_name
    return base


def _add_file_sink(
    *,
    log_dir: str,
    file_name: str,
    level,
    format_string,
    rotation: str,
    retention: str,
    serialize: bool,
    backtrace: bool,
    **kwargs,
) -> None:
    """添加文件日志 sink；目录/文件不可写时降级（仅告警，不中断启动）。

    线上常见场景：容器以非 root 用户运行，挂载的 /app/logs 属主为 root 不可写，
    导致 loguru 创建文件 sink 时抛 PermissionError。日志属于基础设施，绝不应让它
    把整个应用拖垮——故此处捕获 OSError 并降级为仅控制台输出（已在前面添加）。
    """
    try:
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)
        loguru_logger.add(
            str(log_dir_path / file_name),
            level=level,
            format=format_string,
            rotation=rotation,
            retention=retention,
            serialize=serialize,
            catch=True,
            backtrace=backtrace,
            **kwargs,
        )
    except OSError as e:
        sys.stderr.write(
            f"[日志降级] 无法写入日志文件 {log_dir}/{file_name}（{e}）；"
            f"已降级为仅控制台输出，应用继续启动。\n"
        )
        sys.stderr.flush()


def configure_logging(
    level: Union[int, str] = logging.INFO,
    format_string: Optional[str] = None,
    enable_console: bool = True,
    enable_file: bool = False,
    log_dir: str = "logs",
    app_name: str = "app",
    rotation: str = "10 MB",
    retention: str = "30 days",
    serialize: bool = False,
    enable_error_file: bool = False,
    backtrace: bool = False,
    **kwargs,
):
    """配置 loguru 日志系统，支持开发级与线上级两种 profile。

    Args:
        level: 日志级别。
        format_string: 自定义格式字符串（serialize=True 时忽略内容，但仍须为 str）。
        enable_console: 是否启用控制台输出。
        enable_file: 是否启用文件输出（全级别）。
        enable_error_file: 是否启用独立的 ERROR 级别日志文件（线上推荐）。
        log_dir: 日志文件目录。
        app_name: 应用名称。
        rotation: 日志轮转设置。
        retention: 日志保留时间。
        serialize: 是否序列化为 JSON（线上推荐 True）。
        backtrace: 是否记录完整回溯栈（开发推荐 True）。
        **kwargs: 其他 loguru 配置参数。
    """
    loguru_logger.remove()

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    loguru_level = LoguruAdapter("", level)._map_logging_level_to_loguru(level)

    # 同步已缓存适配器的级别，保证 isEnabledFor 与 sink 实际级别一致
    # （级别过滤本身由 sink 完成，这里只让查询接口反映真实配置）。
    for adapter in _adapter_cache.values():
        adapter.setLevel(level)

    # format 兜底：即使 serialize=True，loguru.add() 仍要求 format 为 str/callable
    if format_string is None:
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>"
            "<light-white> | </light-white>"
            "<level>{level: <8}</level>"
            "<light-white> | </light-white>"
            "<cyan>{extra[name]}</cyan>"
            "<light-white> | </light-white>"
            "<level>{message}</level>"
        )

    if enable_console:
        loguru_logger.add(
            sys.stdout,
            level=loguru_level,
            format=format_string,
            serialize=serialize,
            colorize=not serialize,
            catch=True,
            backtrace=backtrace,
            **kwargs,
        )

    if enable_file:
        _add_file_sink(
            log_dir=log_dir,
            file_name=f"{app_name}.log",
            level=loguru_level,
            format_string=format_string,
            rotation=rotation,
            retention=retention,
            serialize=serialize,
            backtrace=backtrace,
            **kwargs,
        )

    if enable_error_file:
        _add_file_sink(
            log_dir=log_dir,
            file_name=f"{app_name}_error.log",
            level="ERROR",
            format_string=format_string,
            rotation=rotation,
            retention=retention,
            serialize=serialize,
            backtrace=True,  # error 日志始终记录完整栈
            **kwargs,
        )
