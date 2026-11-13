from typing import List, Literal, Optional
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
    # 管理展示字段
    display_name: Optional[str] = Field(None, max_length=100)
    is_system: bool = False
    sort_order: int = 0
    model_config = ConfigDict(str_strip_whitespace=True)


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = Field(None, max_length=100)
    sort_order: Optional[int] = None
    model_config = ConfigDict(str_strip_whitespace=True)


class Role(RoleBase, TZModel):
    id: int
    permissions: List[Permission] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AdminRoleCreate(BaseModel):
    """管理员创建角色：name + 展示名 + 描述 + 权限名列表（resource:action）。"""

    name: str = Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1, max_length=32)
    fantasy_display_name: Optional[str] = Field(None, max_length=32)
    description: Optional[str] = Field(None, max_length=200)
    permissions: List[str] = Field(default_factory=list)
    audit_domains: List[str] = Field(default_factory=list)
    model_config = ConfigDict(str_strip_whitespace=True)


class AdminRoleUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=32)
    fantasy_display_name: Optional[str] = Field(None, max_length=32)
    description: Optional[str] = Field(None, max_length=200)
    audit_domains: Optional[List[str]] = None
    model_config = ConfigDict(str_strip_whitespace=True)


class AdminRolePermissions(BaseModel):
    """全量替换角色权限（权限名 resource:action；不存在则自动创建）。"""

    permissions: List[str] = Field(default_factory=list)


class AdminRoleOut(TZModel):
    """管理员视图角色：含权限名列表与用户数。"""

    id: int
    name: str
    display_name: Optional[str] = None
    fantasy_display_name: Optional[str] = None
    description: Optional[str] = None
    is_system: bool = False
    is_protected: bool = False
    sort_order: int = 0
    permissions: List[str] = Field(default_factory=list)
    audit_domains: List[str] = Field(default_factory=list)
    user_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AdminPermissionOut(BaseModel):
    """管理员视图权限点。"""

    id: int
    name: str  # resource:action
    resource: str
    action: str
    description: Optional[str] = None


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


class RoleBindingIn(BaseModel):
    """单条角色绑定：角色 + 作用范围（own / peak / all）。"""

    role_id: int = Field(gt=0)
    scope_type: Literal["own", "peak", "all"] = "own"
    scope_peak_id: Optional[int] = Field(None, gt=0)

    model_config = ConfigDict(extra="forbid")


class RoleBindingsReplace(BaseModel):
    """整组替换用户角色绑定。"""

    bindings: List[RoleBindingIn] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RoleBindingOut(TZModel):
    """用户角色绑定视图。"""

    id: int
    role_id: int
    role_name: str
    display_name: Optional[str] = None
    fantasy_display_name: Optional[str] = None
    scope_type: str
    scope_peak_id: Optional[int] = None
    created_at: Optional[datetime] = None


class UserBindingsResponse(TZModel):
    """用户角色绑定与授权版本。"""

    user_id: int
    authorization_version: int
    bindings: List[RoleBindingOut] = Field(default_factory=list)
