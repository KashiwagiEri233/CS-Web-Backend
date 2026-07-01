from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel

from app.schemas.base import TZModel


class PermissionBase(BaseModel):
    name: str
    resource: str
    action: str
    description: Optional[str] = None


class PermissionCreate(PermissionBase):
    pass


class PermissionUpdate(BaseModel):
    name: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    description: Optional[str] = None


class Permission(PermissionBase, TZModel):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class Role(RoleBase, TZModel):
    id: int
    permissions: List[Permission] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserRoleAssignment(BaseModel):
    user_id: int
    role_id: int


class RolePermissionAssignment(BaseModel):
    role_id: int
    permission_id: int


class UserPermissionCheck(BaseModel):
    resource: str
    action: str


class UserPermissionResult(BaseModel):
    has_permission: bool


class UserPermissionsResponse(BaseModel):
    """用户的权限集合响应（权限已聚合为 "resource:action" 字符串）。"""
    user_id: int
    permissions: List[str] = []