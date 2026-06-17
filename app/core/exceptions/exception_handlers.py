"""
全局异常处理器和中间件
提供统一的异常捕获、处理和日志记录机制
"""

import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Type, Union

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.loguru_logger import get_logger
from app.database import get_session
from .base_exceptions import (
    BaseAppException,
    BusinessException,
    AuthenticationException,
    AuthorizationException,
    ValidationException,
    NotFoundException,
    ConflictException,
    DatabaseException,
    ExternalServiceException,
    RateLimitException
)
from .response_models import (
    ErrorResponse,
    ValidationErrorResponse,
    ErrorContext,
    ErrorDetail
)

logger = get_logger("exception_handler")

_HTTP_ERROR_CODES: Dict[int, str] = {
    401: "AUTHENTICATION_FAILED",
    403: "AUTHORIZATION_FAILED",
    404: "RESOURCE_NOT_FOUND",
    409: "RESOURCE_CONFLICT",
    429: "RATE_LIMIT_EXCEEDED",
}


def create_error_context(request: Request) -> ErrorContext:
    """从请求创建错误上下文"""
    # 尝试从请求状态中获取请求ID
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    
    # 尝试从请求状态中获取用户ID
    user_id = getattr(request.state, 'user_id', None)
    
    # 获取客户端信息
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    return ErrorContext(
        request_id=request_id,
        user_id=user_id,
        ip_address=client_ip,
        user_agent=user_agent,
        endpoint=f"{request.method} {request.url.path}",
        method=request.method,
        timestamp=datetime.now(timezone.utc)
    )


def _build_request_context_dict(request: Request) -> dict:
    """构造写日志库用的请求上下文字典（多处处理器共用）。"""
    return {
        "request_id": getattr(request.state, "request_id", None),
        "user_id": getattr(request.state, "user_id", None),
        "method": request.method,
        "endpoint": f"{request.method} {request.url.path}",
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


async def _record_exception_to_db(
    request: Request,
    record_fn,
    *args,
    log_label: str = "异常",
    traceback_id: Optional[str] = None,
) -> None:
    """把异常/验证错误写入 DB（best-effort）。

    DB 记录失败不影响响应，只记日志。仅在业务异常处理器（健康路径）使用，
    兜底 500 处理器不应调用此函数（见 general_exception_handler 的说明）。
    """
    try:
        async with get_session() as db:
            from app.services.exception_service import ExceptionService

            exception_service = ExceptionService(db)
            await record_fn(
                exception_service,
                request_context=_build_request_context_dict(request),
                *args,
            )
    except Exception as db_error:
        logger.error(
            f"记录{log_label}到数据库失败: {type(db_error).__name__}: {str(db_error)}",
            traceback_id=traceback_id,
        )


def _safe_json_response(
    status_code: int,
    response_model,
    fallback_body: dict,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """优先用 response_model 序列化；失败时回退到 fallback_body。

    headers 用于透传异常携带的自定义响应头（如 OAuth2 的 WWW-Authenticate）。
    """
    try:
        return JSONResponse(
            status_code=status_code,
            content=response_model.model_dump(),
            headers=headers,
        )
    except Exception:
        return JSONResponse(
            status_code=status_code, content=fallback_body, headers=headers
        )


def create_validation_error_response(
    exc: Union[RequestValidationError, ValidationError],
    request: Request,
    status_code: int = 422
) -> ValidationErrorResponse:
    """创建验证错误响应"""
    context = create_error_context(request)
    
    # 处理不同类型的验证错误
    if isinstance(exc, RequestValidationError):
        errors = exc.errors()
    else:
        errors = exc.errors()
    
    validation_errors = []
    for error in errors:
        # 提取字段路径
        field_path = ".".join(str(loc) for loc in error.get("loc", [])) if "loc" in error else None
        
        validation_errors.append(ErrorDetail(
            field=field_path,
            message=error.get("msg", "验证错误"),
            code=error.get("type", "validation_error")
        ))
    
    return ValidationErrorResponse(
        error_code="VALIDATION_FAILED",
        message="数据验证失败",
        status_code=status_code,
        validation_errors=validation_errors,
        context=context,
        traceback_id=str(uuid.uuid4())
    )


def create_app_exception_response(exc: BaseAppException, request: Request) -> ErrorResponse:
    """创建应用程序异常响应"""
    context = create_error_context(request)
    
    # 更新异常的时间戳
    exc.timestamp = datetime.now(timezone.utc)
    
    return ErrorResponse(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details if exc.details else None,
        context=context,
        traceback_id=exc.traceback_id
    )


def create_http_exception_response(exc: Union[HTTPException, StarletteHTTPException], request: Request) -> ErrorResponse:
    """创建HTTP异常响应"""
    context = create_error_context(request)
    status_code = exc.status_code
    
    return ErrorResponse(
        error_code=_HTTP_ERROR_CODES.get(status_code, f"HTTP_{status_code}"),
        message=exc.detail,
        status_code=status_code,
        context=context,
        traceback_id=str(uuid.uuid4())
    )


def create_server_error_response(exc: Exception, request: Request) -> ErrorResponse:
    """创建服务器错误响应"""
    context = create_error_context(request)
    traceback_id = str(uuid.uuid4())
    
    # 记录详细错误信息
    try:
        # 对于 ResponseValidationError，我们需要特别处理，因为它可能包含复杂的信息
        if "ResponseValidationError" in str(type(exc)):
            logger.error(
                f"响应验证错误: {str(exc)}",
                error_type=type(exc).__name__,
                traceback_id=traceback_id,
                exc_info=False  # 避免复杂的异常信息导致更多错误
            )
        else:
            logger.error(
                "未处理的异常",
                error_type=type(exc).__name__,
                error_message=str(exc),
                traceback_id=traceback_id,
                context=context.model_dump() if context else None,
                exc_info=True
            )
    except Exception as log_error:
        # 如果日志记录失败，使用基本日志记录
        logger.error(f"未处理的异常: {type(exc).__name__}: {str(exc)}")
        logger.error(f"日志记录错误: {type(log_error).__name__}: {str(log_error)}")
    
    return ErrorResponse(
        error_code="INTERNAL_SERVER_ERROR",
        message="内部服务器错误",
        status_code=500,
        context=context,
        traceback_id=traceback_id
    )


def create_database_error_response(exc: SQLAlchemyError, request: Request) -> ErrorResponse:
    """创建数据库错误响应"""
    context = create_error_context(request)
    traceback_id = str(uuid.uuid4())
    
    # 确定错误类型和消息
    error_code = "DATABASE_ERROR"
    message = "数据库操作失败"
    details = {}
    
    if isinstance(exc, IntegrityError):
        error_code = "DATABASE_INTEGRITY_ERROR"
        message = "数据库完整性错误"
        # 尝试提取更有用的信息
        if exc.orig:
            details["original_error"] = str(exc.orig)
    
    # 记录错误信息
    try:
        logger.error(
            "数据库异常",
            error_type=type(exc).__name__,
            error_code=error_code,
            error_message=message,
            traceback_id=traceback_id,
            context=context.model_dump() if context else None,
            exc_info=True
        )
    except Exception as log_error:
        # 如果日志记录失败，使用基本日志记录
        logger.error(f"数据库异常: {type(exc).__name__}: {str(exc)}")
        logger.error(f"日志记录错误: {type(log_error).__name__}: {str(log_error)}")
    
    return ErrorResponse(
        error_code=error_code,
        message=message,
        status_code=500,
        details=details,
        context=context,
        traceback_id=traceback_id
    )


async def app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
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

    # 业务异常时 DB 通常健康，记录到 DB（best-effort）
    await _record_exception_to_db(
        request,
        lambda svc, request_context: svc.record_exception(
            exception=exc, request_context=request_context
        ),
        log_label="应用程序异常",
        traceback_id=exc.traceback_id,
    )

    response = create_app_exception_response(exc, request)
    return _safe_json_response(
        exc.status_code,
        response,
        {
            "success": False,
            "error_code": exc.error_code,
            "message": exc.message,
            "status_code": exc.status_code,
            "traceback_id": exc.traceback_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers=getattr(exc, "headers", None),
    )


async def http_exception_handler(request: Request, exc: Union[HTTPException, StarletteHTTPException]) -> JSONResponse:
    """HTTP异常处理器"""
    logger.warning(
        "HTTP异常",
        status_code=exc.status_code,
        error_message=exc.detail,
        method=request.method,
        url=str(request.url),
    )

    await _record_exception_to_db(
        request,
        lambda svc, request_context: svc.record_exception(
            exception=exc, request_context=request_context
        ),
        log_label="HTTP异常",
    )

    response = create_http_exception_response(exc, request)
    return _safe_json_response(
        exc.status_code,
        response,
        {
            "success": False,
            "error_code": f"HTTP_{exc.status_code}",
            "message": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """验证异常处理器"""
    logger.warning(
        "请求验证失败",
        errors=exc.errors(),
        method=request.method,
        url=str(request.url),
    )

    await _record_exception_to_db(
        request,
        lambda svc, request_context: svc.record_validation_error(
            errors=exc.errors(), request_context=request_context
        ),
        log_label="验证错误",
    )

    response = create_validation_error_response(exc, request)
    return _safe_json_response(
        422,
        response,
        {
            "success": False,
            "error_code": "VALIDATION_FAILED",
            "message": "数据验证失败",
            "status_code": 422,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def pydantic_validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Pydantic验证异常处理器（不写 DB：纯 schema 校验失败无需入库）"""
    logger.warning(
        "Pydantic验证失败",
        errors=exc.errors(),
        method=request.method,
        url=str(request.url),
    )

    response = create_validation_error_response(exc, request)
    return _safe_json_response(
        422,
        response,
        {
            "success": False,
            "error_code": "VALIDATION_FAILED",
            "message": "数据验证失败",
            "status_code": 422,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库异常处理器"""
    response = create_database_error_response(exc, request)
    return _safe_json_response(
        500,
        response,
        {
            "success": False,
            "error_code": "DATABASE_ERROR",
            "message": "数据库操作失败",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """通用异常处理器（兜底 500）。

    重要：这里不写数据库。500 异常往往源于 DB 自身故障（连接断、死锁、迁移不一致），
    在此再开 session 写日志会二次失败，且即便 catch 住也会拖慢响应、掩盖原始错误。
    日志走 loguru（stdout/文件），DB 记录由业务异常处理器（健康路径）负责。
    """
    response = create_server_error_response(exc, request)
    return _safe_json_response(
        500,
        response,
        {
            "success": False,
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "内部服务器错误",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def setup_exception_handlers(app: FastAPI) -> None:
    """
    设置全局异常处理器

    注册顺序说明：FastAPI 按异常类型的精确匹配（最具体优先）派发，不依赖注册顺序；
    因此只要每个类型都注册了对应 handler 即可。这里按"业务异常 → HTTP → 验证 →
    数据库 → 兜底 Exception"分组列出，新增异常子类时只需在对应列表里追加。

    Args:
        app: FastAPI应用实例
    """
    # 自定义应用异常（基类 + 所有业务子类，统一走 app_exception_handler）
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
        app.add_exception_handler(exc_type, app_exception_handler)

    # HTTP异常
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # 验证异常
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)

    # 数据库异常（IntegrityError 是 SQLAlchemyError 子类，FastAPI 会按最具体匹配优先）
    app.add_exception_handler(SQLAlchemyError, database_exception_handler)
    app.add_exception_handler(IntegrityError, database_exception_handler)

    # 通用异常处理器（必须放在最后，作为后备）
    app.add_exception_handler(Exception, general_exception_handler)


class ExceptionHandlerMiddleware:
    """异常处理中间件"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # 创建请求对象用于错误上下文
        from fastapi import Request
        request = Request(scope, receive)
        
        # 生成请求ID并存储在状态中
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            # 注意：中间件层抛出的异常不会经过 app.add_exception_handler 注册的处理器
            # （那些只覆盖路由层），必须在此按类型显式区分，否则 HTTPException 与业务异常
            # 会被错误地吞成 500。
            if isinstance(exc, (HTTPException, StarletteHTTPException)):
                response = create_http_exception_response(exc, request)
                # HTTPException 自带 headers（如 OAuth2 的 WWW-Authenticate）
                extra_headers = getattr(exc, "headers", None)
            elif isinstance(exc, BaseAppException):
                response = create_app_exception_response(exc, request)
                # 业务异常可通过 BaseAppException.headers 携带自定义响应头
                extra_headers = getattr(exc, "headers", None)
            else:
                response = create_server_error_response(exc, request)
                extra_headers = None

            try:
                # 创建响应，使用 model_dump 来正确处理 datetime
                content = response.model_dump()
                response_obj = JSONResponse(
                    status_code=response.status_code,
                    content=content,
                    headers=extra_headers,
                )
            except Exception as json_error:
                # 如果序列化失败，使用基本错误响应（保留原始状态码）
                content = {
                    "success": False,
                    "error_code": response.error_code if response else "INTERNAL_SERVER_ERROR",
                    "message": response.message if response else "内部服务器错误",
                    "status_code": response.status_code if response else 500,
                    "traceback_id": response.traceback_id if response else None,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                response_obj = JSONResponse(
                    status_code=response.status_code if response else 500,
                    content=content,
                    headers=extra_headers,
                )

            # 发送响应
            await response_obj(scope, receive, send)