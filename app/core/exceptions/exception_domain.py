"""领域/业务专用异常子类（用户、权限等）。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .error_codes import ErrorCode
from .exception_http import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    NotFoundException,
)


class UserAlreadyExistsException(ConflictException):
    """用户已存在异常"""

    def __init__(
        self,
        username: Optional[str] = None,
        email: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        message_parts = []
        error_details = details or {}

        if username:
            message_parts.append(f"用户名 '{username}'")
            error_details["username"] = username

        if email:
            message_parts.append(f"邮箱 '{email}'")
            error_details["email"] = email

        message = (
            f"{' 和 '.join(message_parts)} 已存在" if message_parts else "用户已存在"
        )

        super().__init__(
            message=message,
            error_code=ErrorCode.Conflict.USER_ALREADY_EXISTS,
            details=error_details,
        )


class InvalidCredentialsException(AuthenticationException):
    """无效凭据异常"""

    def __init__(self, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message="用户名或密码错误",
            error_code=ErrorCode.Auth.INVALID_CREDENTIALS,
            details=details,
        )


class UserNotActiveException(AuthenticationException):
    """用户未激活异常"""

    def __init__(
        self,
        user_id: Optional[Union[str, int]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        error_details = details or {}
        if user_id is not None:
            error_details["user_id"] = str(user_id)
            message = f"用户 {user_id} 未激活"
        else:
            message = "用户账户未激活"

        super().__init__(
            message=message,
            error_code=ErrorCode.Auth.USER_NOT_ACTIVE,
            details=error_details,
        )


class PermissionDeniedException(AuthorizationException):
    """权限拒绝异常"""

    def __init__(
        self,
        required_permissions: Optional[list] = None,
        details: Optional[Dict[str, Any]] = None,
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
            details=error_details,
        )


class ResourceNotFoundException(NotFoundException):
    """通用资源未找到异常"""

    def __init__(
        self,
        resource_type: str,
        resource_id: Optional[Union[str, int]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=f"{resource_type} 未找到",
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
