"""用户管理相关 schema。

UserCreate / UserUpdate 统一复用 schemas.auth 中的定义（含密码强度、用户名、
邮箱、full_name 校验），避免两处定义造成校验规则漂移（如曾出现用户管理接口
绕过密码强度校验的缺陷）。UserResponse / UserInDB 为本模块特有响应模型。
"""

from pydantic import ConfigDict

from app.schemas.auth import UserBase, UserCreate, UserUpdate

__all__ = ["UserBase", "UserCreate", "UserUpdate", "UserResponse", "UserInDB"]


class UserResponse(UserBase):
    id: int
    is_superuser: bool

    model_config = ConfigDict(from_attributes=True)


class UserInDB(UserResponse):
    hashed_password: str
