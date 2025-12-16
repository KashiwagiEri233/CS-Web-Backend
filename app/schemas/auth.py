from typing import Optional

from pydantic import BaseModel


class UserBase(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool = True


from typing import Optional, Any
from pydantic import BaseModel, field_validator, EmailStr, ConfigDict
from app.core.validators import (
    validate_password_strength, 
    validate_username, 
    validate_email,
    sanitize_input
)


class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool = True
    
    @field_validator('username')
    @classmethod
    def validate_username_field(cls, v: str) -> str:
        is_valid, error_msg = validate_username(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v
    
    @field_validator('full_name')
    @classmethod
    def sanitize_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return sanitize_input(v, max_length=100)
        return v


class UserCreate(UserBase):
    password: str
    model_config = ConfigDict(str_strip_whitespace=True)
    
    @field_validator('password')
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
    
    @field_validator('password')
    @classmethod
    def validate_password_field(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            is_valid, error_msg = validate_password_strength(v)
            if not is_valid:
                raise ValueError(error_msg)
        return v
    
    @field_validator('full_name')
    @classmethod
    def sanitize_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return sanitize_input(v, max_length=100)
        return v


class User(UserBase):
    id: int
    is_superuser: bool
    
    class Config:
        from_attributes = True


# 别名，用于API响应
UserResponse = User


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None


class LoginRequest(BaseModel):
    username: str
    password: str