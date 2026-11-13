"""用户管理相关 schema。

UserCreate / UserUpdate / UserResponse 统一复用 schemas.auth 中的定义（含密码强度、
用户名、邮箱、full_name 校验），避免两处定义造成校验规则漂移（如曾出现用户管理
接口绕过密码强度校验的缺陷、UserResponse 双定义漂移）。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, field_validator

from app.core.validators import validate_password_strength
from app.schemas.auth import User, UserBase, UserCreate, UserOut, UserUpdate
from app.schemas.base import camel_config
from app.schemas.profile import ProfileUpdate

__all__ = [
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "AdminUserUpdate",
    "AdminUserListOut",
    "CustomResetPassword",
    "InternalUserUpsertIn",
]

# 单一定义来源：用户响应模型即 auth.User（id + is_superuser + 基础字段）。
UserResponse = User

# 可管理的角色（前端 admin 语义；root = is_superuser，不在此列）
MANAGEABLE_ROLES = [
    "user",
    "admin",
    "content_moderator",
    "exam_admin",
    "task_publisher",
]


class AdminUserUpdate(ProfileUpdate):
    """管理员编辑用户：资料字段 + 角色 + 激活状态。"""

    role: Optional[str] = None
    is_active: Optional[bool] = None
    model_config = camel_config(str_strip_whitespace=True)

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in MANAGEABLE_ROLES:
            raise ValueError(f"角色必须为 {' / '.join(MANAGEABLE_ROLES)}")
        return v


class AdminUserOut(UserOut):
    """管理员视图用户：附角色列表。"""

    roles: List[str] = []


class AdminUserListOut(BaseModel):
    """管理员用户列表（分页 + 筛选）。"""

    users: List[AdminUserOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    model_config = camel_config()


class CustomResetPassword(BaseModel):
    """超级管理员自定义重置密码。"""

    password: str
    model_config = camel_config(str_strip_whitespace=True)

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class InternalUserUpsertIn(BaseModel):
    """旧项目回推用户入参（POST /internal/users/upsert）。

    字段与旧项目 InternalUserUpsertDTO 对齐；邮箱是两侧账号唯一标识，必填。
    回推语义：按 email 查重后关联既有账号或创建新账号，不生成占位邮箱。
    """

    sync_id: Optional[str] = None
    username: Optional[str] = None
    email: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    # 旧项目 bcrypt 哈希（两侧算法一致，可直接复制）
    password_hash: Optional[str] = None
    active: Optional[bool] = None
    model_config = camel_config(str_strip_whitespace=True)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or "@" not in v:
            raise ValueError("邮箱格式非法")
        return v
