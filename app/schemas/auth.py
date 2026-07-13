from typing import Optional

from pydantic import BaseModel, field_validator, EmailStr, ConfigDict

from app.core.validators import (
    MAX_EMAIL_LENGTH,
    validate_password_strength,
    validate_username,
)


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


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenPair(BaseModel):
    """登录/刷新返回：access + refresh 双 token。

    access token 短期（默认 15 分钟），refresh token 长期（默认 7 天）。
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access token 有效期（秒），便于前端调度刷新


class RefreshRequest(BaseModel):
    """用 refresh token 换新 access token 的请求体。"""

    refresh_token: str


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None


class LoginRequest(BaseModel):
    username: str
    password: str
