"""全局异常处理器注册与路由层 handler。

响应构造见 ``error_builders``；中间件见 ``exception_middleware``；
共用工具见 ``handler_utils``。
"""

from __future__ import annotations

from typing import Any, Union, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.loguru_logger import get_logger
from app.core.config import settings
from app.core.timezone import now_utc

from .base_exceptions import (
    AuthenticationException,
    AuthorizationException,
    BaseAppException,
    BusinessException,
    ConflictException,
    DatabaseException,
    ExternalServiceException,
    NotFoundException,
    RateLimitException,
    ValidationException,
)
from .error_builders import (
    _serialize_validation_errors,
    create_app_exception_response,
    create_database_error_response,
    create_http_exception_response,
    create_server_error_response,
    create_validation_error_response,
)
from .error_codes import ErrorCode
from .exception_middleware import ExceptionHandlerMiddleware
from .handler_utils import record_exception_to_db, safe_json_response

logger = get_logger("exception_handler")

# 对外 re-export，保持 ``from .exception_handlers import ExceptionHandlerMiddleware`` 可用
__all__ = [
    "setup_exception_handlers",
    "ExceptionHandlerMiddleware",
    "app_exception_handler",
    "http_exception_handler",
    "validation_exception_handler",
    "pydantic_validation_exception_handler",
    "database_exception_handler",
    "general_exception_handler",
]


async def app_exception_handler(
    request: Request, exc: BaseAppException
) -> JSONResponse:
    """应用程序异常处理器"""
    logger.warning(
        "应用程序异常",
        error_code=exc.error_code,
        error_message=exc.message,
        status_code=exc.status_code,
        traceback_id=exc.traceback_id,
        details=exc.details,
        context=exc.context,
        exc_info=exc.cause is not None,
    )

    if settings.PERSIST_CLIENT_ERRORS or exc.status_code >= 500:
        await record_exception_to_db(
            request,
            lambda svc, request_context: svc.record_exception(
                exception=exc, request_context=request_context
            ),
            log_label="应用程序异常",
            traceback_id=exc.traceback_id,
        )

    response = create_app_exception_response(exc, request)
    return safe_json_response(
        exc.status_code,
        response,
        {
            "success": False,
            "error_code": exc.error_code,
            "message": exc.message,
            "status_code": exc.status_code,
            "traceback_id": exc.traceback_id,
            "timestamp": now_utc().isoformat(),
        },
        headers=getattr(exc, "headers", None),
    )


async def http_exception_handler(
    request: Request, exc: Union[HTTPException, StarletteHTTPException]
) -> JSONResponse:
    """HTTP 异常处理器"""
    logger.warning(
        "HTTP异常",
        status_code=exc.status_code,
        error_message=exc.detail,
        method=request.method,
        path=request.url.path,
    )

    if settings.PERSIST_CLIENT_ERRORS or exc.status_code >= 500:
        await record_exception_to_db(
            request,
            lambda svc, request_context: svc.record_exception(
                exception=exc, request_context=request_context
            ),
            log_label="HTTP异常",
        )

    response = create_http_exception_response(exc, request)
    return safe_json_response(
        exc.status_code,
        response,
        {
            "success": False,
            "error_code": f"HTTP_{exc.status_code}",
            "message": exc.detail,
            "status_code": exc.status_code,
            "timestamp": now_utc().isoformat(),
        },
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """验证异常处理器"""
    safe_errors = _serialize_validation_errors(exc.errors())
    logger.warning(
        "请求验证失败",
        errors=safe_errors,
        method=request.method,
        path=request.url.path,
    )

    if settings.PERSIST_CLIENT_ERRORS:
        await record_exception_to_db(
            request,
            lambda svc, request_context: svc.record_validation_error(
                errors=safe_errors, request_context=request_context
            ),
            log_label="验证错误",
        )

    response = create_validation_error_response(exc, request)
    return safe_json_response(
        422,
        response,
        {
            "success": False,
            "error_code": ErrorCode.Validation.VALIDATION_FAILED,
            "message": "数据验证失败",
            "status_code": 422,
            "timestamp": now_utc().isoformat(),
        },
    )


async def pydantic_validation_exception_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """Pydantic 验证异常处理器（不写 DB：纯 schema 校验失败无需入库）"""
    safe_errors = _serialize_validation_errors(exc.errors())
    logger.warning(
        "Pydantic验证失败",
        errors=safe_errors,
        method=request.method,
        path=request.url.path,
    )

    response = create_validation_error_response(exc, request)
    return safe_json_response(
        422,
        response,
        {
            "success": False,
            "error_code": ErrorCode.Validation.VALIDATION_FAILED,
            "message": "数据验证失败",
            "status_code": 422,
            "timestamp": now_utc().isoformat(),
        },
    )


async def database_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """数据库异常处理器"""
    response = create_database_error_response(exc, request)
    return safe_json_response(
        500,
        response,
        {
            "success": False,
            "error_code": ErrorCode.Database.DATABASE_ERROR,
            "message": "数据库操作失败",
            "status_code": 500,
            "timestamp": now_utc().isoformat(),
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """通用异常处理器（兜底 500）。

    重要：这里不写数据库。500 异常往往源于 DB 自身故障，再开 session 写日志会二次失败。
    """
    response = create_server_error_response(exc, request)
    return safe_json_response(
        500,
        response,
        {
            "success": False,
            "error_code": ErrorCode.System.INTERNAL_SERVER_ERROR,
            "message": "内部服务器错误",
            "status_code": 500,
            "timestamp": now_utc().isoformat(),
        },
    )


def setup_exception_handlers(app: FastAPI) -> None:
    """设置全局异常处理器。

    FastAPI 按异常类型精确匹配（最具体优先）派发，不依赖注册顺序。
    按「业务异常 → HTTP → 验证 → 数据库 → 兜底 Exception」分组列出。
    """
    # 各 handler 的 exc 参数比 Exception 更窄；FastAPI 类型存根会误报 arg-type。

    app_exception_types = (
        BaseAppException,
        BusinessException,
        AuthenticationException,
        AuthorizationException,
        ValidationException,
        NotFoundException,
        ConflictException,
        DatabaseException,
        ExternalServiceException,
        RateLimitException,
    )
    for exc_type in app_exception_types:
        app.add_exception_handler(exc_type, cast(Any, app_exception_handler))

    app.add_exception_handler(HTTPException, cast(Any, http_exception_handler))
    app.add_exception_handler(StarletteHTTPException, cast(Any, http_exception_handler))

    app.add_exception_handler(
        RequestValidationError, cast(Any, validation_exception_handler)
    )
    app.add_exception_handler(
        ValidationError, cast(Any, pydantic_validation_exception_handler)
    )

    app.add_exception_handler(SQLAlchemyError, cast(Any, database_exception_handler))
    app.add_exception_handler(IntegrityError, cast(Any, database_exception_handler))

    app.add_exception_handler(Exception, general_exception_handler)
