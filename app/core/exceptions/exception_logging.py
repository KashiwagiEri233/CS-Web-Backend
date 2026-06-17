"""
异常日志记录系统
提供结构化的异常日志记录功能（分析/指标/告警已移除）
"""

import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.loguru_logger import get_logger
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

        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    "traceback_id": exception.traceback_id or log_record["traceback_id"],
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

        self.logger.error(
            "异常发生",
            exception_type=exception_type,
            exception_message=exception_message,
            error_code=log_record.get("error_code"),
            status_code=log_record.get("status_code"),
            traceback_id=log_record.get("traceback_id"),
            request_id=request_context.get("request_id") if request_context else None,
            user_id=request_context.get("user_id") if request_context else None,
            endpoint=request_context.get("endpoint") if request_context else None,
            exc_info=True,
        )

        return log_record

    def log_validation_error(
        self,
        errors: List[Dict[str, Any]],
        request_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录验证错误，返回日志记录字典。"""
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
