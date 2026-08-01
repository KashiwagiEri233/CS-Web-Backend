from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, field_validator, ConfigDict

from app.core.validators import (
    MAX_EMAIL_LENGTH,
    validate_password_strength,
    validate_username,
)
from app.schemas.base import TZModel


class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool = True

    @field_validator("username")
    @classmethod
    def validate_username_field(cls, v: str) -> str:
        is_valid, error_msg = validate_username(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v

    @field_validator("email")
    @classmethod
    def validate_email_length(cls, v: EmailStr) -> EmailStr:
        if len(str(v)) > MAX_EMAIL_LENGTH:
            raise ValueError(f"邮箱长度不能超过{MAX_EMAIL_LENGTH}个字符")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 100:
            raise ValueError("全名长度不能超过100个字符")
        return v


class UserCreate(UserBase):
    password: str
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    # 自助改密（PUT /users/me）时必填：校验当前密码，防 access token 泄露被接管。
    # 管理端重置（PUT /users/{id}）由 UserService.update_user 忽略本字段。
    old_password: Optional[str] = None
    is_active: Optional[bool] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("email")
    @classmethod
    def validate_email_length(cls, v: Optional[EmailStr]) -> Optional[EmailStr]:
        if v is not None and len(str(v)) > MAX_EMAIL_LENGTH:
            raise ValueError(f"邮箱长度不能超过{MAX_EMAIL_LENGTH}个字符")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            is_valid, error_msg = validate_password_strength(v)
            if not is_valid:
                raise ValueError(error_msg)
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 100:
            raise ValueError("全名长度不能超过100个字符")
        return v


class User(UserBase):
    id: int
    is_superuser: bool

    model_config = ConfigDict(from_attributes=True)


# 别名，用于API响应
UserResponse = User


class UserOut(TZModel):
    """用户出参（含业务资料字段，Phase 1 迁移）。"""

    id: int
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_type: str = "initial"
    github_url: Optional[str] = None
    website_url: Optional[str] = None
    tech_tags: List[str] = []
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime


class MeResponse(TZModel):
    """GET /auth/me 响应：用户 + 角色 + 2FA 状态。"""

    user: UserOut
    roles: List[str] = []
    two_factor_enabled: bool = False


class RegisterRequest(BaseModel):
    """注册：邮箱 + 密码 + 邮箱验证码。"""

    email: EmailStr
    password: str
    code: str
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("email")
    @classmethod
    def validate_email_length(cls, v: EmailStr) -> EmailStr:
        if len(str(v)) > MAX_EMAIL_LENGTH:
            raise ValueError(f"邮箱长度不能超过{MAX_EMAIL_LENGTH}个字符")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class SendCodeRequest(BaseModel):
    """发送邮箱验证码。"""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email_length(cls, v: EmailStr) -> EmailStr:
        if len(str(v)) > MAX_EMAIL_LENGTH:
            raise ValueError(f"邮箱长度不能超过{MAX_EMAIL_LENGTH}个字符")
        return v


class ForgotPasswordRequest(BaseModel):
    """忘记密码：提交密码重置申请。"""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email_length(cls, v: EmailStr) -> EmailStr:
        if len(str(v)) > MAX_EMAIL_LENGTH:
            raise ValueError(f"邮箱长度不能超过{MAX_EMAIL_LENGTH}个字符")
        return v


class TokenPair(BaseModel):
    """登录/刷新返回：access + refresh 双 token。

    access token 短期（默认 15 分钟），refresh token 长期（默认 7 天）。
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access token 有效期（秒），便于前端调度刷新


class LoginResponse(BaseModel):
    """邮箱登录响应：2FA 未启用直接返回 token；已启用返回预认证 token。"""

    requires_2fa: bool = False
    two_factor_token: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: Optional[str] = None
    expires_in: Optional[int] = None


class RefreshRequest(BaseModel):
    """用 refresh token 换新 access token 的请求体。"""

    refresh_token: str


class LoginRequest(BaseModel):
    username: str
    password: str


class EmailLoginRequest(BaseModel):
    """邮箱登录（前端主路径）。"""

    email: EmailStr
    password: str
    model_config = ConfigDict(str_strip_whitespace=True)


class TwoFactorSetupResponse(BaseModel):
    """2FA 初始化：secret + otpauth URI + 一次性备用码（未启用，待 confirm）。"""

    secret: str
    otpauth_uri: str
    backup_codes: List[str]


class TwoFactorCodeRequest(BaseModel):
    """2FA 确认 / 禁用 / 重新生成备用码：TOTP 或备用码。"""

    code: str


class TwoFactorVerifyRequest(BaseModel):
    """2FA 验证码接口：mode=setup（登录态确认启用）或 mode=login（登录二次验证）。"""

    mode: str = "login"
    code: str
    two_factor_token: Optional[str] = None


class TwoFactorStatusResponse(BaseModel):
    """GET /auth/2fa：状态查询。"""

    enabled: bool
    setup: bool
