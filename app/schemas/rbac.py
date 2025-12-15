from typing import List, Optional

from pydantic import BaseModel


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


class Permission(PermissionBase):
    id: int
    
    class Config:
        from_attributes = True


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


class Role(RoleBase):
    id: int
    permissions: List[Permission] = []
    
    class Config:
        from_attributes = True


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