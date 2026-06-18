"""
基于loguru的日志系统实现
提供与标准库logging兼容的接口，同时使用loguru作为底层日志处理
"""

import json
import logging
import sys
import uuid
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union
from pathlib import Path
from contextvars import ContextVar

try:
    # Python 3.9+ 标准库时区支持（跨平台，无需 time.tzset）
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from loguru import logger as loguru_logger

loguru_logger.level("TRACE", color="<blue>")
loguru_logger.level("DEBUG", color="<cyan>")
loguru_logger.level("INFO", color="<green>")
loguru_logger.level("WARNING", color="<yellow>")
loguru_logger.level("ERROR", color="<red>")
loguru_logger.level("CRITICAL", color="<red><bold>")


_DISPLAY_KEY_MAP: Dict[str, str] = {
    "type": "数据库类型",
    "version": "版本",
    "tables_found": "已找到表数量",
    "total_checked": "检查表总数",
    "table_list": "表列表",
    "method": "请求方法",
    "url": "请求URL",
    "status_code": "响应状态码",
    "process_time": "处理时间",
    "client_ip": "客户端IP",
    "user_agent": "用户代理",
    "error_type": "错误类型",
    "error_message": "错误消息",
    "traceback_id": "追踪ID",
    "request_id": "请求ID",
    "context": "上下文",
}


class _DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


# 上下文变量用于存储请求级别的信息
_logging_context: ContextVar[Dict[str, Any]] = ContextVar("logging_context", default={})


class LoguruAdapter:
    """
    Loguru适配器，提供与标准库logging.Logger兼容的接口
    """

    def __init__(self, name: str, level: Union[int, str] = logging.INFO):
        """初始化适配器"""
        self.name = name
        self._logger = loguru_logger.bind(name=name)

        # 仅记录级别用于 isEnabledFor 判断，不触碰全局 handler 配置
        # handler 的添加由 configure_logging 统一管理，避免每次 get_logger 重置全局
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.level = level

    def setLevel(self, level: Union[int, str]) -> None:
        """设置该适配器的日志级别（仅影响本实例的 isEnabledFor 判断）"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.level = level

    def _map_logging_level_to_loguru(self, level: int) -> str:
        """将logging级别映射到loguru级别"""
        if level >= logging.CRITICAL:
            return "CRITICAL"
        elif level >= logging.ERROR:
            return "ERROR"
        elif level >= logging.WARNING:
            return "WARNING"
        elif level >= logging.INFO:
            return "INFO"
        else:
            return "DEBUG"

    def isEnabledFor(self, level: Union[int, str]) -> bool:
        """检查是否启用指定级别的日志"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        return level >= self.level

    def _log(
        self,
        level: int,
        msg: str,
        args,
        exc_info=None,
        extra=None,
        stack_info=False,
        **kwargs,
    ):
        """内部日志记录方法"""
        if not self.isEnabledFor(level):
            return

        # 添加日志级别名称
        level_name = logging.getLevelName(level)

        # 使用loguru记录日志
        log_method = getattr(self._logger, level_name.lower(), self._logger.info)

        # 格式化参数信息
        if kwargs:
            # 创建格式化的参数字符串
            formatted_params = []
            for k, v in kwargs.items():
                if k == "name":
                    continue

                display_key = _DISPLAY_KEY_MAP.get(k, k)

                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False, cls=_DateTimeEncoder)

                formatted_params.append(f" [{display_key}]: {v}")

            # 将格式化的参数添加到消息中
            if formatted_params:
                msg = f"{msg}" + "".join(formatted_params)

        # 记录日志。注意：
        # 1) 不向 loguru 传任何额外位置/关键字参数，否则 loguru 会对 msg 调用 .format()，
        #    当 msg 含 JSON（如 {"request_id": ...}）时触发 KeyError。
        # 2) loguru 用 opt(exception=...) 传递异常信息，而非 stdlib 的 exc_info=。
        if exc_info:
            self._logger.opt(exception=exc_info).log(level_name, msg)
        else:
            log_method(msg)

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
        kwargs.setdefault("exc_info", True)
        self.error(msg, *args, **kwargs)

    def bind(self, **kwargs) -> "LoguruAdapter":
        """绑定上下文信息，返回新的适配器实例"""
        # 创建新实例
        new_adapter = LoguruAdapter(self.name, self.level)

        # 绑定到loguru日志器
        new_adapter._logger = self._logger.bind(**kwargs)

        return new_adapter

    def unbind(self, *keys) -> "LoguruAdapter":
        """解绑指定的上下文信息"""
        # 创建新实例
        new_adapter = LoguruAdapter(self.name, self.level)

        # 获取当前绑定信息
        # 注意：loguru没有直接的unbind方法，我们只能重新创建
        return new_adapter

    def new(self, **kwargs) -> "LoguruAdapter":
        """创建全新的适配器实例，不继承当前上下文"""
        new_adapter = LoguruAdapter(self.name, self.level)
        new_adapter._logger = self._logger.bind(**kwargs)
        return new_adapter

    def get_context(self) -> Dict[str, Any]:
        """获取当前上下文信息"""
        return _logging_context.get().copy()

    def addHandler(self, hdlr):
        """添加处理器（兼容性方法）"""
        # loguru使用不同的处理器系统，这里只做兼容性处理
        pass

    def removeHandler(self, hdlr):
        """移除处理器（兼容性方法）"""
        # loguru使用不同的处理器系统，这里只做兼容性处理
        pass


# 全局适配器缓存
_adapter_cache: Dict[str, LoguruAdapter] = {}


def get_logger(name: str = None) -> LoguruAdapter:
    """
    获取日志适配器实例

    Args:
        name: 日志器名称，默认使用调用模块名

    Returns:
        LoguruAdapter实例
    """
    if name is None:
        # 自动获取调用模块名
        import inspect

        frame = inspect.currentframe().f_back
        name = frame.f_globals.get("__name__", "unknown")

    # 缓存管理
    if name not in _adapter_cache:
        _adapter_cache[name] = LoguruAdapter(name)

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

    def bind(self, **kwargs) -> "LoggingContextManager":
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
    return str(uuid.uuid4()).replace("-", "")


# 兼容标准库logging的模块级别函数
def getLogger(name: str = None) -> LoguruAdapter:
    """兼容标准库logging.getLogger"""
    return get_logger(name)


def basicConfig(**kwargs):
    """兼容标准库logging.basicConfig"""
    level = kwargs.get("level", logging.INFO)
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # 设置所有已创建适配器的级别
    for adapter in _adapter_cache.values():
        adapter.setLevel(level)

    # 配置loguru
    loguru_level = LoguruAdapter("", level)._map_logging_level_to_loguru(level)

    # 移除所有现有的处理器
    loguru_logger.remove()

    # 重新添加处理器
    format_str = kwargs.get(
        "format",
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>"
        "<light-white> | </light-white>"
        "<level>{level: <8}</level>"
        "<light-white> | </light-white>"
        "<cyan>{extra[name]}</cyan>"
        "<light-white> | </light-white>"
        "\n"
        "<level>→ {message}</level>",
    )

    loguru_logger.add(
        kwargs.get("stream", sys.stdout),
        level=loguru_level,
        format=format_str,
        serialize=kwargs.get("serialize", False),
        colorize=True,  # 启用颜色
        catch=True,  # 捕获异常
    )


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
        profile: 日志 profile，dev 或 prod
        level: 日志级别，留空用 profile 默认
        serialize: 是否 JSON 序列化，None 用 profile 默认
        backtrace: 是否完整回溯栈，None 用 profile 默认
        enable_console: 是否控制台输出，None 用 profile 默认
        enable_file: 是否文件输出，None 用 profile 默认
        enable_error_file: 是否独立 error 文件，None 用 profile 默认
        log_dir: 日志目录
        rotation: 轮转大小
        retention: 保留时间
        app_name: 应用名称

    Returns:
        configure_logging 的完整参数 dict
    """
    base = LOG_PROFILES.get(profile, LOG_PROFILES["dev"]).copy()

    # 显式传参覆盖 profile 默认值
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
        # 不能用 loguru 自身记录（此刻文件 sink 尚未建立），直接写 stderr 保证可见
        sys.stderr.write(
            f"[日志降级] 无法写入日志文件 {log_dir}/{file_name}（{e}）；"
            f"已降级为仅控制台输出，应用继续启动。\n"
        )
        sys.stderr.flush()


# 配置函数
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
    """
    配置loguru日志系统，支持开发级与线上级两种 profile。

    Args:
        level: 日志级别
        format_string: 自定义格式字符串（serialize=True 时忽略）
        enable_console: 是否启用控制台输出
        enable_file: 是否启用文件输出（全级别）
        enable_error_file: 是否启用独立的 ERROR 级别日志文件（线上推荐）
        log_dir: 日志文件目录
        app_name: 应用名称
        rotation: 日志轮转设置
        retention: 日志保留时间
        serialize: 是否序列化为 JSON（线上推荐 True）
        backtrace: 是否记录完整回溯栈（开发推荐 True）
        **kwargs: 其他 loguru 配置参数
    """
    # 移除所有现有的处理器
    loguru_logger.remove()

    # 设置级别
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    loguru_level = LoguruAdapter("", level)._map_logging_level_to_loguru(level)

    # format 兜底：即使 serialize=True（JSON 输出时 format 不影响内容），loguru.add() 仍会
    # 校验 format 必须是 str/callable，传 None 会抛 TypeError——故 format_string 为 None 时
    # 必须始终赋默认值，不能仅在 not serialize 时赋值（否则生产 serialize=True 直接启动崩溃）。
    if format_string is None:
        # 分隔符 | 显式用 <light-white>（亮白），避免回退到不可控的终端默认配色（曾显示为红色）
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>"
            "<light-white> | </light-white>"
            "<level>{level: <8}</level>"
            "<light-white> | </light-white>"
            "<cyan>{extra[name]}</cyan>"
            "<light-white> | </light-white>"
            "<level>{message}</level>"
        )

    # 添加控制台处理器（开发环境主输出）
    if enable_console:
        loguru_logger.add(
            sys.stdout,
            level=loguru_level,
            format=format_string,
            serialize=serialize,
            colorize=not serialize,  # JSON 输出时禁用颜色
            catch=True,
            backtrace=backtrace,
            **kwargs,
        )

    # 添加全级别文件处理器
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

    # 添加独立 ERROR 级别文件处理器（线上排障用）
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
    """将标准库 logging 的输出重定向到 loguru，实现统一日志格式"""

    def emit(self, record: logging.LogRecord) -> None:
        # 获取对应的 loguru 级别
        try:
            level: Union[str, int] = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到真正的调用栈深度，让 loguru 显示正确的模块/行号
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # 用 record.name 绑定 extra[name]，匹配 format 中的 {extra[name]}
        loguru_logger.opt(depth=depth, exception=record.exc_info).bind(
            name=record.name
        ).log(level, record.getMessage())


def setup_uvicorn_logging() -> None:
    """将 uvicorn / 标准 logging 的输出拦截到 loguru，统一日志格式"""
    # 替换 uvicorn 所有 logger 的 handler
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = [InterceptHandler()]
        uv_logger.propagate = False


def _apply_timezone_patcher(timezone_name: str) -> None:
    """通过 loguru patcher 把每条日志记录的时间转换为指定时区。

    跨平台方案：使用 zoneinfo（Python 3.9+ 标准库），不依赖 time.tzset()（POSIX 专用，
    Windows 不支持）。仅影响日志展示层；数据库仍以 UTC 存储带时区列。

    背景：config 里有 TIMEZONE 配置项（含校验与 tzinfo 属性），但若不在此应用，
    loguru 会默认用机器本地时间打日志——配置项形同虚设（UTC 容器里日志显示 UTC，
    与 TIMEZONE 设置无关）。本函数把该配置真正接到日志层。

    Args:
        timezone_name: IANA 时区名（如 "Asia/Shanghai"、"UTC"）。无效则回退到 UTC。
    """
    if ZoneInfo is None:
        # Python < 3.9 无 zoneinfo，跳过（loguru 默认用本地时间）
        return

    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        # 无效时区名，回退到 UTC 避免日志崩溃
        tz = timezone.utc

    def _timezone_patcher(record):
        # loguru 的 record["time"] 是带时区的 datetime（本地）；转换为配置时区用于展示
        record["time"] = record["time"].astimezone(tz)
        return record

    loguru_logger.configure(patcher=_timezone_patcher)


def init_logging(settings) -> None:
    """根据 settings 一键初始化日志（run.py 与应用启动 lifespan 共用）。

    关键：uvicorn 开启 reload 时，server 在**子进程**里重新 import 应用，run.py 的 main()
    不会在该子进程执行——必须在 lifespan 启动时再调用一次，保证子进程也用统一格式，否则会
    回退到 loguru 默认格式（来源恒显示为 loguru_logger:_log，且分隔符配色不可控）。
    幂等：configure_logging 内部先 remove 再 add。

    Args:
        settings: 应用配置实例（含 LOG_* 字段）。以参数传入，避免本模块反向依赖 config。
    """
    # 应用时区：通过 patcher 把每条日志记录的时间转换为配置时区（如 Asia/Shanghai）。
    # 跨平台方案：使用 zoneinfo（Python 3.9+ 标准库），不依赖 time.tzset()（POSIX 专用）。
    # 注意：数据库仍以 UTC 存储带时区列；此转换仅影响日志展示层。
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


# 注意：不在模块级别初始化配置，由应用程序统一配置（run.py / lifespan 调用 init_logging）
