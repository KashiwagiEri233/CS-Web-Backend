"""自定义异常类体系（兼容入口）。

实现已按职责拆到：
- ``exception_base``：BaseAppException
- ``exception_http``：HTTP 语义族（401/403/404/…）
- ``exception_domain``：用户/权限等领域子类

本模块 re-export 全部符号，保持
``from app.core.exceptions.base_exceptions import NotFoundException`` 等路径不变。
"""

from .exception_base import BaseAppException
from .exception_domain import (
    InvalidCredentialsException,
    PermissionDeniedException,
    ResourceNotFoundException,
    UserAlreadyExistsException,
    UserNotActiveException,
)
from .exception_http import (
    AuthenticationException,
    AuthorizationException,
    BusinessException,
    ConflictException,
    DatabaseException,
    ExternalServiceException,
    NotFoundException,
    RateLimitException,
    ValidationException,
)

__all__ = [
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
]
