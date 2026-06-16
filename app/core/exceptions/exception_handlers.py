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
from app.database import get_db
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
    # 记录异常信息
    logger.warning(
        "应用程序异常",
        error_code=exc.error_code,
        error_message=exc.message,
        status_code=exc.status_code,
        traceback_id=exc.traceback_id,
        details=exc.details,
        context=exc.context,
        exc_info=exc.cause is not None
    )
    
    # 尝试将异常记录到数据库
    try:
        # 获取数据库会话
        async for db in get_db():
            # 创建异常服务实例
            from app.services.exception_service import ExceptionService
            exception_service = ExceptionService(db)
            
            # 准备请求上下文
            request_context = {
                "request_id": getattr(request.state, 'request_id', None),
                "user_id": getattr(request.state, 'user_id', None),
                "method": request.method,
                "endpoint": f"{request.method} {request.url.path}",
                "ip_address": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent")
            }
            
            # 记录异常到数据库
            await exception_service.record_exception(
                exception=exc,
                request_context=request_context
            )
            break  # 只需要第一个数据库会话
    except Exception as db_error:
        # 数据库记录失败不影响主流程，只记录错误日志
        logger.error(
            f"记录异常到数据库失败: {type(db_error).__name__}: {str(db_error)}",
            traceback_id=exc.traceback_id
        )
    
    response = create_app_exception_response(exc, request)
    try:
        return JSONResponse(
            status_code=exc.status_code,
            content=response.model_dump()
        )
    except Exception as json_error:
        # 如果序列化失败，使用基本错误响应
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error_code": exc.error_code,
                "message": exc.message,
                "status_code": exc.status_code,
                "traceback_id": exc.traceback_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


async def http_exception_handler(request: Request, exc: Union[HTTPException, StarletteHTTPException]) -> JSONResponse:
    """HTTP异常处理器"""
    # 记录HTTP异常信息
    logger.warning(
        "HTTP异常",
        status_code=exc.status_code,
        error_message=exc.detail,
        method=request.method,
        url=str(request.url)
    )
    
    # 尝试将异常记录到数据库
    try:
        # 获取数据库会话
        async for db in get_db():
            # 创建异常服务实例
            from app.services.exception_service import ExceptionService
            exception_service = ExceptionService(db)
            
            # 准备请求上下文
            request_context = {
                "request_id": getattr(request.state, 'request_id', None),
                "user_id": getattr(request.state, 'user_id', None),
                "method": request.method,
                "endpoint": f"{request.method} {request.url.path}",
                "ip_address": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent")
            }
            
            # 记录异常到数据库
            await exception_service.record_exception(
                exception=exc,
                request_context=request_context
            )
            break  # 只需要第一个数据库会话
    except Exception as db_error:
        # 数据库记录失败不影响主流程，只记录错误日志
        logger.error(
            f"记录HTTP异常到数据库失败: {type(db_error).__name__}: {str(db_error)}"
        )
    
    response = create_http_exception_response(exc, request)
    try:
        return JSONResponse(
            status_code=exc.status_code,
            content=response.model_dump()
        )
    except Exception as json_error:
        # 如果序列化失败，使用基本错误响应
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error_code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
                "status_code": exc.status_code,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """验证异常处理器"""
    # 记录验证错误
    logger.warning(
        "请求验证失败",
        errors=exc.errors(),
        method=request.method,
        url=str(request.url)
    )
    
    # 尝试将验证错误记录到数据库
    try:
        # 获取数据库会话
        async for db in get_db():
            # 创建异常服务实例
            from app.services.exception_service import ExceptionService
            exception_service = ExceptionService(db)
            
            # 准备请求上下文
            request_context = {
                "request_id": getattr(request.state, 'request_id', None),
                "user_id": getattr(request.state, 'user_id', None),
                "method": request.method,
                "endpoint": f"{request.method} {request.url.path}",
                "ip_address": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent")
            }
            
            # 记录验证错误到数据库
            await exception_service.record_validation_error(
                errors=exc.errors(),
                request_context=request_context
            )
            break  # 只需要第一个数据库会话
    except Exception as db_error:
        # 数据库记录失败不影响主流程，只记录错误日志
        logger.error(
            f"记录验证错误到数据库失败: {type(db_error).__name__}: {str(db_error)}"
        )
    
    response = create_validation_error_response(exc, request)
    try:
        return JSONResponse(
            status_code=422,
            content=response.model_dump()
        )
    except Exception as json_error:
        # 如果序列化失败，使用基本错误响应
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error_code": "VALIDATION_FAILED",
                "message": "数据验证失败",
                "status_code": 422,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


async def pydantic_validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Pydantic验证异常处理器"""
    # 记录验证错误
    logger.warning(
        "Pydantic验证失败",
        errors=exc.errors(),
        method=request.method,
        url=str(request.url)
    )
    
    response = create_validation_error_response(exc, request)
    try:
        return JSONResponse(
            status_code=422,
            content=response.model_dump()
        )
    except Exception as json_error:
        # 如果序列化失败，使用基本错误响应
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error_code": "VALIDATION_FAILED",
                "message": "数据验证失败",
                "status_code": 422,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库异常处理器"""
    response = create_database_error_response(exc, request)
    try:
        return JSONResponse(
            status_code=500,
            content=response.model_dump()
        )
    except Exception as json_error:
        # 如果序列化失败，使用基本错误响应
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error_code": "DATABASE_ERROR",
                "message": "数据库操作失败",
                "status_code": 500,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """通用异常处理器"""
    response = create_server_error_response(exc, request)
    
    # 尝试将异常记录到数据库
    try:
        # 获取数据库会话
        async for db in get_db():
            # 创建异常服务实例
            from app.services.exception_service import ExceptionService
            exception_service = ExceptionService(db)
            
            # 准备请求上下文
            request_context = {
                "request_id": getattr(request.state, 'request_id', None),
                "user_id": getattr(request.state, 'user_id', None),
                "method": request.method,
                "endpoint": f"{request.method} {request.url.path}",
                "ip_address": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent")
            }
            
            # 记录异常到数据库
            await exception_service.record_exception(
                exception=exc,
                request_context=request_context
            )
            break  # 只需要第一个数据库会话
    except Exception as db_error:
        # 数据库记录失败不影响主流程，只记录错误日志
        logger.error(
            f"记录异常到数据库失败: {type(db_error).__name__}: {str(db_error)}",
            traceback_id=response.traceback_id if response else None
        )
    
    try:
        return JSONResponse(
            status_code=500,
            content=response.model_dump()
        )
    except Exception as json_error:
        # 如果序列化失败，使用基本错误响应
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "内部服务器错误",
                "status_code": 500,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


def setup_exception_handlers(app: FastAPI) -> None:
    """
    设置全局异常处理器
    
    Args:
        app: FastAPI应用实例
    """
    # 自定义应用程序异常
    app.add_exception_handler(BaseAppException, app_exception_handler)
    
    # 业务异常子类
    app.add_exception_handler(BusinessException, app_exception_handler)
    app.add_exception_handler(AuthenticationException, app_exception_handler)
    app.add_exception_handler(AuthorizationException, app_exception_handler)
    app.add_exception_handler(ValidationException, app_exception_handler)
    app.add_exception_handler(NotFoundException, app_exception_handler)
    app.add_exception_handler(ConflictException, app_exception_handler)
    app.add_exception_handler(DatabaseException, app_exception_handler)
    app.add_exception_handler(ExternalServiceException, app_exception_handler)
    app.add_exception_handler(RateLimitException, app_exception_handler)
    
    # HTTP异常
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    
    # 验证异常
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)
    
    # 数据库异常
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
            elif isinstance(exc, BaseAppException):
                response = create_app_exception_response(exc, request)
            else:
                response = create_server_error_response(exc, request)

            try:
                # 创建响应，使用 model_dump 来正确处理 datetime
                content = response.model_dump()
                response_obj = JSONResponse(
                    status_code=response.status_code,
                    content=content
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
                    content=content
                )

            # 发送响应
            await response_obj(scope, receive, send)