"""
自定义异常类体系
定义了应用程序的各种异常类型，提供统一的错误处理机制
"""

import traceback
from datetime import datetime
from typing import Any, Dict, Optional, Union
from uuid import uuid4

from .error_codes import ErrorCode


class BaseAppException(Exception):
    """
    应用程序基础异常类
    所有自定义异常的基础类，提供统一的错误处理机制
    """
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        """
        初始化基础异常
        
        Args:
            message: 错误消息
            error_code: 自定义错误代码
            status_code: HTTP状态码
            details: 错误详细信息
            context: 错误上下文信息
            cause: 原始异常对象
            headers: 附加到 HTTP 响应的自定义头（如 OAuth2 的 WWW-Authenticate）
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.status_code = status_code
        self.details = details or {}
        self.context = context or {}
        self.cause = cause
        self.headers = headers
        self.traceback_id = str(uuid4())  # 用于跟踪异常的唯一ID
        self.timestamp: Optional[datetime] = None  # 将在处理器中设置
    
    def to_dict(self) -> Dict[str, Any]:
        """将异常转换为字典格式"""
        result = {
            "error_code": self.error_code,
            "message": self.message,
            "status_code": self.status_code,
            "traceback_id": self.traceback_id
        }
        
        if self.details:
            result["details"] = self.details
            
        if self.context:
            result["context"] = self.context
            
        if self.cause:
            result["cause"] = str(self.cause)
            
        if self.timestamp:
            result["timestamp"] = self.timestamp.isoformat()
            
        return result
    
    def __str__(self) -> str:
        """字符串表示"""
        return f"[{self.error_code}] {self.message}"
    
    def __repr__(self) -> str:
        """调试表示"""
        return f"{self.__class__.__name__}(message='{self.message}', error_code='{self.error_code}', status_code={self.status_code})"


class BusinessException(BaseAppException):
    """业务逻辑异常"""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Business.BUSINESS_ERROR,
            status_code=400,
            details=details,
            context=context
        )


class AuthenticationException(BaseAppException):
    """认证异常"""
    
    def __init__(
        self,
        message: str = "认证失败",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
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
            headers=headers
        )


class AuthorizationException(BaseAppException):
    """授权异常"""
    
    def __init__(
        self,
        message: str = "权限不足",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Authorization.AUTHORIZATION_FAILED,
            status_code=403,
            details=details,
            context=context
        )


class ValidationException(BaseAppException):
    """验证异常"""
    
    def __init__(
        self,
        message: str = "数据验证失败",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Validation.VALIDATION_FAILED,
            status_code=422,
            details=details,
            context=context
        )


class NotFoundException(BaseAppException):
    """资源未找到异常"""
    
    def __init__(
        self,
        message: str = "资源未找到",
        resource_type: Optional[str] = None,
        resource_id: Optional[Union[str, int]] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        # 构建详细的错误信息
        if resource_type and resource_id:
            detailed_message = f"{resource_type} (ID: {resource_id}) 未找到"
        elif resource_type:
            detailed_message = f"{resource_type} 未找到"
        else:
            detailed_message = message
            
        # 设置详细信息
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
            context=context
        )


class ConflictException(BaseAppException):
    """冲突异常"""
    
    def __init__(
        self,
        message: str = "资源冲突",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            error_code=error_code or ErrorCode.Conflict.RESOURCE_CONFLICT,
            status_code=409,
            details=details,
            context=context
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
        cause: Optional[Exception] = None
    ):
        # 构建详细的错误信息
        if operation and table:
            detailed_message = f"数据库操作失败: {operation} on {table}"
        elif operation:
            detailed_message = f"数据库操作失败: {operation}"
        else:
            detailed_message = message
            
        # 设置详细信息
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
            cause=cause
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
        cause: Optional[Exception] = None
    ):
        # 构建详细的错误信息
        if service_name:
            detailed_message = f"外部服务调用失败: {service_name}"
        else:
            detailed_message = message
            
        # 设置详细信息
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
            cause=cause
        )


class RateLimitException(BaseAppException):
    """限流异常"""
    
    def __init__(
        self,
        message: str = "请求频率超限",
        limit: Optional[int] = None,
        window: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        # 设置详细信息
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
            context=context
        )


# 预定义的业务异常子类
class UserAlreadyExistsException(ConflictException):
    """用户已存在异常"""
    
    def __init__(
        self,
        username: Optional[str] = None,
        email: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        message_parts = []
        error_details = details or {}
        
        if username:
            message_parts.append(f"用户名 '{username}'")
            error_details["username"] = username
            
        if email:
            message_parts.append(f"邮箱 '{email}'")
            error_details["email"] = email
            
        message = f"{' 和 '.join(message_parts)} 已存在" if message_parts else "用户已存在"
        
        super().__init__(
            message=message,
            error_code=ErrorCode.Conflict.USER_ALREADY_EXISTS,
            details=error_details
        )


class InvalidCredentialsException(AuthenticationException):
    """无效凭据异常"""
    
    def __init__(self, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message="用户名或密码错误",
            error_code=ErrorCode.Auth.INVALID_CREDENTIALS,
            details=details
        )


class UserNotActiveException(AuthenticationException):
    """用户未激活异常"""
    
    def __init__(self, user_id: Optional[Union[str, int]] = None, details: Optional[Dict[str, Any]] = None):
        error_details = details or {}
        if user_id is not None:
            error_details["user_id"] = str(user_id)
            message = f"用户 {user_id} 未激活"
        else:
            message = "用户账户未激活"
            
        super().__init__(
            message=message,
            error_code=ErrorCode.Auth.USER_NOT_ACTIVE,
            details=error_details
        )


class PermissionDeniedException(AuthorizationException):
    """权限拒绝异常"""
    
    def __init__(
        self,
        required_permissions: Optional[list] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        error_details = details or {}
        if required_permissions:
            error_details["required_permissions"] = required_permissions
            message = f"权限不足，需要权限: {', '.join(required_permissions)}"
        else:
            message = "权限不足"
            
        super().__init__(
            message=message,
            error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            details=error_details
        )


class ResourceNotFoundException(NotFoundException):
    """通用资源未找到异常"""
    
    def __init__(
        self,
        resource_type: str,
        resource_id: Optional[Union[str, int]] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=f"{resource_type} 未找到",
            resource_type=resource_type,
            resource_id=resource_id,
            details=details
        )