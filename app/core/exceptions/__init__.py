"""
FastAPI应用的异常处理模块
提供自定义异常类体系、全局异常处理器和统一错误响应格式
"""

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
    RateLimitException,
    UserAlreadyExistsException,
    InvalidCredentialsException,
    UserNotActiveException,
    PermissionDeniedException,
    ResourceNotFoundException
)

from .exception_handlers import (
    setup_exception_handlers,
    ExceptionHandlerMiddleware
)

from .response_models import (
    ErrorResponse,
    ErrorDetail,
    ErrorContext
)

__all__ = [
    # 异常类
    "BaseAppException",
    "BusinessException",
    "AuthenticationException", 
    "AuthorizationException",
    "ValidationException",
    "NotFoundException",
    "ConflictException",
    "DatabaseException",
    "ExternalServiceException",
    "RateLimitException",
    "UserAlreadyExistsException",
    "InvalidCredentialsException",
    "UserNotActiveException",
    "PermissionDeniedException",
    "ResourceNotFoundException",
    
    # 异常处理
    "setup_exception_handlers",
    "ExceptionHandlerMiddleware",
    
    # 响应模型
    "ErrorResponse",
    "ErrorDetail",
    "ErrorContext"
]