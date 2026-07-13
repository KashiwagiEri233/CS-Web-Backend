"""Loguru 适配器：与标准库 logging.Logger 兼容的接口，底层走 loguru。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Union

from loguru import logger as loguru_logger

from .context import _logging_context

# 模块导入时配置 loguru 级别颜色（幂等，重复调用安全）
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


class LoguruAdapter:
    """Loguru 适配器，提供与标准库 logging.Logger 兼容的接口。"""

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
        """将 logging 级别映射到 loguru 级别"""
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

        level_name = logging.getLevelName(level)
        log_method = getattr(self._logger, level_name.lower(), self._logger.info)

        if kwargs:
            formatted_params = []
            for k, v in kwargs.items():
                if k == "name":
                    continue

                display_key = _DISPLAY_KEY_MAP.get(k, k)

                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False, cls=_DateTimeEncoder)

                formatted_params.append(f" [{display_key}]: {v}")

            if formatted_params:
                msg = f"{msg}" + "".join(formatted_params)

        # 1) 不向 loguru 传额外位置/关键字参数，否则 loguru 会对 msg 调用 .format()，
        #    当 msg 含 JSON 时触发 KeyError。
        # 2) loguru 用 opt(exception=...) 传递异常，而非 stdlib 的 exc_info=。
        if exc_info:
            self._logger.opt(exception=exc_info).log(level_name, msg)
        else:
            log_method(msg)

    def debug(self, msg: str, *args, **kwargs):
        """记录 DEBUG 级别日志"""
        self._log(logging.DEBUG, msg, args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """记录 INFO 级别日志"""
        self._log(logging.INFO, msg, args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """记录 WARNING 级别日志"""
        self._log(logging.WARNING, msg, args, **kwargs)

    def warn(self, msg: str, *args, **kwargs):
        """warning 的别名"""
        self.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """记录 ERROR 级别日志"""
        self._log(logging.ERROR, msg, args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """记录 CRITICAL 级别日志"""
        self._log(logging.CRITICAL, msg, args, **kwargs)

    def fatal(self, msg: str, *args, **kwargs):
        """critical 的别名"""
        self.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """记录异常信息，自动添加异常信息"""
        kwargs.setdefault("exc_info", True)
        self.error(msg, *args, **kwargs)

    def bind(self, **kwargs) -> "LoguruAdapter":
        """绑定上下文信息，返回新的适配器实例"""
        new_adapter = LoguruAdapter(self.name, self.level)
        new_adapter._logger = self._logger.bind(**kwargs)
        return new_adapter

    def unbind(self, *keys) -> "LoguruAdapter":
        """解绑指定的上下文信息"""
        # loguru 无直接 unbind；返回干净实例
        return LoguruAdapter(self.name, self.level)

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
        pass

    def removeHandler(self, hdlr):
        """移除处理器（兼容性方法）"""
        pass


# 全局适配器缓存
_adapter_cache: Dict[str, LoguruAdapter] = {}


def get_logger(name: Optional[str] = None) -> LoguruAdapter:
    """获取日志适配器实例。

    Args:
        name: 日志器名称，默认使用调用模块名。

    Returns:
        LoguruAdapter 实例。
    """
    if name is None:
        import inspect

        frame = inspect.currentframe().f_back
        name = frame.f_globals.get("__name__", "unknown")

    if name not in _adapter_cache:
        _adapter_cache[name] = LoguruAdapter(name)

    return _adapter_cache[name]


def getLogger(name: Optional[str] = None) -> LoguruAdapter:
    """兼容标准库 logging.getLogger"""
    return get_logger(name)


def basicConfig(**kwargs):
    """兼容标准库 logging.basicConfig"""
    import sys

    level = kwargs.get("level", logging.INFO)
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    for adapter in _adapter_cache.values():
        adapter.setLevel(level)

    loguru_level = LoguruAdapter("", level)._map_logging_level_to_loguru(level)
    loguru_logger.remove()

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
        colorize=True,
        catch=True,
    )
