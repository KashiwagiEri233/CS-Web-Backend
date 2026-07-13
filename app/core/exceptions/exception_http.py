"""HTTP 语义族异常（按状态码分类的通用业务异常）。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .error_codes import ErrorCode
from .exception_base import BaseAppException


class BusinessException(BaseAppException):
    """业务逻辑异常"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Business.BUSINESS_ERROR,
            status_code=400,
            details=details,
            context=context,
        )


class AuthenticationException(BaseAppException):
    """认证异常"""

    def __init__(
        self,
        message: str = "认证失败",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        # OAuth2 规范要求 401 响应携带 WWW-Authenticate 头；
        # 调用方未显式传入时默认带 Bearer scheme。
        if headers is None:
            headers = {"WWW-Authenticate": "Bearer"}
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Auth.AUTHENTICATION_FAILED,
            status_code=401,
            details=details,
            context=context,
            headers=headers,
        )


class AuthorizationException(BaseAppException):
    """授权异常"""

    def __init__(
        self,
        message: str = "权限不足",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Authorization.AUTHORIZATION_FAILED,
            status_code=403,
            details=details,
            context=context,
        )


class ValidationException(BaseAppException):
    """验证异常"""

    def __init__(
        self,
        message: str = "数据验证失败",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Validation.VALIDATION_FAILED,
            status_code=422,
            details=details,
            context=context,
        )


class NotFoundException(BaseAppException):
    """资源未找到异常"""

    def __init__(
        self,
        message: str = "资源未找到",
        resource_type: Optional[str] = None,
        resource_id: Optional[Union[str, int]] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        if resource_type and resource_id:
            detailed_message = f"{resource_type} (ID: {resource_id}) 未找到"
        elif resource_type:
            detailed_message = f"{resource_type} 未找到"
        else:
            detailed_message = message

        error_details = details or {}
        if resource_type:
            error_details["resource_type"] = resource_type
        if resource_id is not None:
            error_details["resource_id"] = str(resource_id)

        super().__init__(
            message=detailed_message,
            error_code=ErrorCode.NotFound.RESOURCE_NOT_FOUND,
            status_code=404,
            details=error_details,
            context=context,
        )


class ConflictException(BaseAppException):
    """冲突异常"""

    def __init__(
        self,
        message: str = "资源冲突",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Conflict.RESOURCE_CONFLICT,
            status_code=409,
            details=details,
            context=context,
        )


class DatabaseException(BaseAppException):
    """数据库异常"""

    def __init__(
        self,
        message: str = "数据库操作失败",
        operation: Optional[str] = None,
        table: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        if operation and table:
            detailed_message = f"数据库操作失败: {operation} on {table}"
        elif operation:
            detailed_message = f"数据库操作失败: {operation}"
        else:
            detailed_message = message

        error_details = details or {}
        if operation:
            error_details["operation"] = operation
        if table:
            error_details["table"] = table

        super().__init__(
            message=detailed_message,
            error_code=ErrorCode.Database.DATABASE_ERROR,
            status_code=500,
            details=error_details,
            context=context,
            cause=cause,
        )


class ExternalServiceException(BaseAppException):
    """外部服务异常"""

    def __init__(
        self,
        message: str = "外部服务调用失败",
        service_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        status_code: int = 502,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        if service_name:
            detailed_message = f"外部服务调用失败: {service_name}"
        else:
            detailed_message = message

        error_details = details or {}
        if service_name:
            error_details["service_name"] = service_name
        if endpoint:
            error_details["endpoint"] = endpoint

        super().__init__(
            message=detailed_message,
            error_code=ErrorCode.ExternalService.EXTERNAL_SERVICE_ERROR,
            status_code=status_code,
            details=error_details,
            context=context,
            cause=cause,
        )


class RateLimitException(BaseAppException):
    """限流异常"""

    def __init__(
        self,
        message: str = "请求频率超限",
        limit: Optional[int] = None,
        window: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        error_details = details or {}
        if limit:
            error_details["limit"] = limit
        if window:
            error_details["window_seconds"] = window

        super().__init__(
            message=message,
            error_code=ErrorCode.RateLimit.RATE_LIMIT_EXCEEDED,
            status_code=429,
            details=error_details,
            context=context,
        )
