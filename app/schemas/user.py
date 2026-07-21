"""用户管理相关 schema。

UserCreate / UserUpdate / UserResponse 统一复用 schemas.auth 中的定义（含密码强度、
用户名、邮箱、full_name 校验），避免两处定义造成校验规则漂移（如曾出现用户管理
接口绕过密码强度校验的缺陷、UserResponse 双定义漂移）。
"""

from app.schemas.auth import User, UserBase, UserCreate, UserUpdate

__all__ = ["UserBase", "UserCreate", "UserUpdate", "UserResponse"]

# 单一定义来源：用户响应模型即 auth.User（id + is_superuser + 基础字段）。
UserResponse = User
