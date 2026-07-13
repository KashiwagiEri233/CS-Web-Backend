"""错误响应体构造：从 Request/异常 → ErrorResponse / ValidationErrorResponse。"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Sequence, Union

from fastapi import Request
from fastapi.exceptions import HTTPException, RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.loguru_logger import get_logger
from app.core.request_context import get_client_meta
from app.core.timezone import now_utc

from .base_exceptions import BaseAppException
from .error_codes import ErrorCode
from .response_models import (
    ErrorContext,
    ErrorDetail,
    ErrorResponse,
    ValidationErrorResponse,
)

logger = get_logger("exception_handler")

# HTTP 状态码 → 错误码注册表。键为状态码，值取自 ErrorCode 命名空间，
# 与对应业务异常子类保持同一事实源（修改错误码只需改 error_codes.py）。
_HTTP_ERROR_CODES: Dict[int, str] = {
    401: ErrorCode.Auth.AUTHENTICATION_FAILED,
    403: ErrorCode.Authorization.AUTHORIZATION_FAILED,
    404: ErrorCode.NotFound.RESOURCE_NOT_FOUND,
    409: ErrorCode.Conflict.RESOURCE_CONFLICT,
    429: ErrorCode.RateLimit.RATE_LIMIT_EXCEEDED,
}


def create_error_context(request: Request) -> ErrorContext:
    """从请求创建错误上下文"""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    user_id = getattr(request.state, "user_id", None)
    client_meta = get_client_meta(request)

    return ErrorContext(
        request_id=request_id,
        user_id=user_id,
        ip_address=client_meta["ip_address"],
        user_agent=client_meta["user_agent"],
        endpoint=f"{request.method} {request.url.path}",
        method=request.method,
        timestamp=now_utc(),
    )


def _serialize_validation_errors(errors: Sequence[Any]) -> List[Dict[str, Any]]:
    """把 Pydantic 校验错误转成可安全记录的 JSON 结构。

    Pydantic v2 在 field_validator 抛 ValueError 时，会在 error["ctx"]["error"]
    里塞入原始异常对象；error["input"] 还可能包含密码、token 等原始输入。
    日志和异常表都不应保存这些值。
    """
    safe: List[Dict[str, Any]] = []
    for error in errors:
        item = dict(error)
        item.pop("input", None)
        ctx = item.get("ctx")
        if isinstance(ctx, dict):
            item["ctx"] = {
                k: (str(v) if isinstance(v, BaseException) else v)
                for k, v in ctx.items()
            }
        safe.append(item)
    return safe


def create_validation_error_response(
    exc: Union[RequestValidationError, ValidationError],
    request: Request,
    status_code: int = 422,
) -> ValidationErrorResponse:
    """创建验证错误响应"""
    context = create_error_context(request)
    errors = exc.errors()

    validation_errors = []
    for error in errors:
        field_path = (
            ".".join(str(loc) for loc in error.get("loc", []))
            if "loc" in error
            else None
        )
        validation_errors.append(
            ErrorDetail(
                field=field_path,
                message=error.get("msg", "验证错误"),
                code=error.get("type", "validation_error"),
            )
        )

    return ValidationErrorResponse(
        error_code=ErrorCode.Validation.VALIDATION_FAILED,
        message="数据验证失败",
        status_code=status_code,
        validation_errors=validation_errors,
        context=context,
        traceback_id=str(uuid.uuid4()),
    )


def create_app_exception_response(
    exc: BaseAppException, request: Request
) -> ErrorResponse:
    """创建应用程序异常响应"""
    context = create_error_context(request)
    exc.timestamp = now_utc()

    return ErrorResponse(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details if exc.details else None,
        context=context,
        traceback_id=exc.traceback_id,
    )


def create_http_exception_response(
    exc: Union[HTTPException, StarletteHTTPException], request: Request
) -> ErrorResponse:
    """创建 HTTP 异常响应"""
    context = create_error_context(request)
    status_code = exc.status_code

    return ErrorResponse(
        error_code=_HTTP_ERROR_CODES.get(status_code, f"HTTP_{status_code}"),
        message=exc.detail,
        status_code=status_code,
        context=context,
        traceback_id=str(uuid.uuid4()),
    )


def create_server_error_response(exc: Exception, request: Request) -> ErrorResponse:
    """创建服务器错误响应"""
    context = create_error_context(request)
    traceback_id = str(uuid.uuid4())

    try:
        if "ResponseValidationError" in str(type(exc)):
            logger.error(
                f"响应验证错误: {str(exc)}",
                error_type=type(exc).__name__,
                traceback_id=traceback_id,
                exc_info=False,
            )
        else:
            logger.error(
                "未处理的异常",
                error_type=type(exc).__name__,
                error_message=str(exc),
                traceback_id=traceback_id,
                context=context.model_dump() if context else None,
                exc_info=True,
            )
    except Exception as log_error:
        logger.error(f"未处理的异常: {type(exc).__name__}: {str(exc)}")
        logger.error(f"日志记录错误: {type(log_error).__name__}: {str(log_error)}")

    return ErrorResponse(
        error_code=ErrorCode.System.INTERNAL_SERVER_ERROR,
        message="内部服务器错误",
        status_code=500,
        context=context,
        traceback_id=traceback_id,
    )


def create_database_error_response(
    exc: SQLAlchemyError, request: Request
) -> ErrorResponse:
    """创建数据库错误响应"""
    context = create_error_context(request)
    traceback_id = str(uuid.uuid4())

    error_code = ErrorCode.Database.DATABASE_ERROR
    message = "数据库操作失败"
    details: Dict[str, Any] = {}

    if isinstance(exc, IntegrityError):
        error_code = ErrorCode.Database.DATABASE_INTEGRITY_ERROR
        message = "数据库完整性错误"
        # 原始数据库错误可能包含表名、约束、SQL 片段或字段值，只写服务端日志，
        # 绝不通过 API details 返回。

    try:
        logger.error(
            "数据库异常",
            error_type=type(exc).__name__,
            error_code=error_code,
            error_message=message,
            traceback_id=traceback_id,
            context=context.model_dump() if context else None,
            exc_info=True,
        )
    except Exception as log_error:
        logger.error(f"数据库异常: {type(exc).__name__}: {str(exc)}")
        logger.error(f"日志记录错误: {type(log_error).__name__}: {str(log_error)}")

    return ErrorResponse(
        error_code=error_code,
        message=message,
        status_code=500,
        details=details,
        context=context,
        traceback_id=traceback_id,
    )
