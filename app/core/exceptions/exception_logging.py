"""
异常日志记录系统
提供结构化的异常日志记录功能（分析/指标/告警已移除）
"""

import traceback
import uuid
from typing import Any, Dict, List, Optional

from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.loguru_logger import get_logger
from app.core.timezone import now_utc
from .base_exceptions import BaseAppException


class ExceptionLogger:
    """异常日志记录器"""

    def __init__(self):
        self.logger = get_logger("exception_logging")

    def log_exception(
        self,
        exception: Exception,
        request_context: Optional[Dict[str, Any]] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录异常信息，返回日志记录字典。"""
        exception_type = type(exception).__name__
        exception_message = str(exception)
        traceback_str = traceback.format_exc()

        # 显式声明为 Dict[str, Any]：日志记录是异构字典（value 含 str/int/dict/None 等多种类型），
        # 否则静态检查器会从字面量把类型收窄为 dict[str, str]，导致后续 update() 误报类型冲突。
        log_record: Dict[str, Any] = {
            "timestamp": now_utc().isoformat(),
            "traceback_id": str(uuid.uuid4()),
            "exception_type": exception_type,
            "exception_message": exception_message,
            "traceback": traceback_str,
        }

        if isinstance(exception, BaseAppException):
            log_record.update(
                {
                    "error_code": exception.error_code,
                    "status_code": exception.status_code,
                    "traceback_id": exception.traceback_id
                    or log_record["traceback_id"],
                    "details": exception.details,
                    "context": exception.context,
                }
            )
        elif isinstance(exception, StarletteHTTPException):
            log_record["status_code"] = exception.status_code
            log_record["error_code"] = f"HTTP_{exception.status_code}"

        if request_context:
            log_record["request_context"] = request_context

        if additional_data:
            log_record["additional_data"] = additional_data

        # 按严重性分级：4xx 客户端错误（如 favicon.ico 的 404、422 校验失败）降级为 WARNING
        # 且不打印堆栈，避免噪音淹没真正的服务端异常；5xx 与未预期异常仍用 ERROR + 完整堆栈。
        status_code = log_record.get("status_code")
        is_client_error = isinstance(status_code, int) and 400 <= status_code < 500

        log_kwargs = dict(
            exception_type=exception_type,
            exception_message=exception_message,
            error_code=log_record.get("error_code"),
            status_code=status_code,
            traceback_id=log_record.get("traceback_id"),
            request_id=request_context.get("request_id") if request_context else None,
            user_id=request_context.get("user_id") if request_context else None,
            endpoint=request_context.get("endpoint") if request_context else None,
        )

        if is_client_error:
            self.logger.warning("客户端异常", **log_kwargs)
        else:
            self.logger.error("异常发生", **log_kwargs, exc_info=True)

        return log_record

    def log_validation_error(
        self,
        errors: List[Dict[str, Any]],
        request_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录验证错误，返回日志记录字典。"""
        log_record: Dict[str, Any] = {
            "timestamp": now_utc().isoformat(),
            "error_type": "validation_error",
            "errors": errors,
        }

        if request_context:
            log_record["request_context"] = request_context

        self.logger.warning(
            "验证错误",
            error_count=len(errors),
            errors=errors,
            request_id=request_context.get("request_id") if request_context else None,
            endpoint=request_context.get("endpoint") if request_context else None,
        )

        return log_record
