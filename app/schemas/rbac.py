from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import TZModel


class PermissionBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    resource: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]*$")
    action: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]*$")
    description: Optional[str] = None
    model_config = ConfigDict(str_strip_whitespace=True)


class PermissionCreate(PermissionBase):
    pass


class PermissionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    resource: Optional[str] = Field(
        None, min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]*$"
    )
    action: Optional[str] = Field(
        None, min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]*$"
    )
    description: Optional[str] = None
    model_config = ConfigDict(str_strip_whitespace=True)


class Permission(PermissionBase, TZModel):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RoleBase(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: bool = True
    model_config = ConfigDict(str_strip_whitespace=True)


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    model_config = ConfigDict(str_strip_whitespace=True)


class Role(RoleBase, TZModel):
    id: int
    permissions: List[Permission] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserRoleAssignment(BaseModel):
    user_id: int = Field(gt=0)
    role_id: int = Field(gt=0)


class RolePermissionAssignment(BaseModel):
    role_id: int = Field(gt=0)
    permission_id: int = Field(gt=0)


class UserPermissionCheck(BaseModel):
    resource: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]*$")
    action: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]*$")


class UserPermissionResult(BaseModel):
    has_permission: bool


class UserPermissionsResponse(BaseModel):
    """用户的权限集合响应（权限已聚合为 "resource:action" 字符串）。"""

    user_id: int
    permissions: List[str] = Field(default_factory=list)
