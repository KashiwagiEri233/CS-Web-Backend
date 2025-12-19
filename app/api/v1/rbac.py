from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_active_user, get_current_superuser
from app.models.user import User
from app.repositories.rbac_repo import RBACRepository
from app.repositories.user_repo import UserRepository
from app.schemas.rbac import (
    Role, RoleCreate, RoleUpdate,
    Permission, PermissionCreate, PermissionUpdate,
    UserRoleAssignment, RolePermissionAssignment,
    UserPermissionCheck, UserPermissionResult
)
from app.services.rbac_service import RBACService

router = APIRouter()


# 角色管理
@router.get("/roles", response_model=List[Role])
async def get_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取所有角色（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    roles = await rbac_repo.get_all_roles()
    return roles


@router.post("/roles", response_model=Role)
async def create_role(
    role_data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """创建角色（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    
    # 检查角色名称是否已存在
    existing_roles = await rbac_repo.get_all_roles()
    for role in existing_roles:
        if role.name == role_data.name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="角色名称已存在"
            )
    
    role_dict = {
        "name": role_data.name,
        "description": role_data.description,
        "is_active": role_data.is_active
    }
    
    created_role = await rbac_repo.create_role(role_dict)
    return created_role


@router.get("/roles/{role_id}", response_model=Role)
async def get_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取指定角色信息（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    role = await rbac_repo.get_role_with_permissions(role_id)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )
    
    return role


@router.put("/roles/{role_id}", response_model=Role)
async def update_role(
    role_id: int,
    role_data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """更新角色（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    role = await rbac_repo.get_role_by_id(role_id)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )
    
    # 更新角色信息
    if role_data.name is not None:
        role.name = role_data.name
    if role_data.description is not None:
        role.description = role_data.description
    if role_data.is_active is not None:
        role.is_active = role_data.is_active
    
    # 更新角色
    await db.commit()
    
    # 预加载权限关系，避免 MissingGreenlet 错误
    stmt = select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
    result = await db.execute(stmt)
    updated_role = result.scalar_one()
    return updated_role


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """删除角色（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    success = await rbac_repo.delete_role(role_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )
    
    return {"message": "角色已删除"}


# 权限管理
@router.get("/permissions", response_model=List[Permission])
async def get_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取所有权限（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    permissions = await rbac_repo.get_all_permissions()
    return permissions


@router.post("/permissions", response_model=Permission)
async def create_permission(
    permission_data: PermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """创建权限（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    
    # 检查权限名称是否已存在
    existing_permissions = await rbac_repo.get_all_permissions()
    for perm in existing_permissions:
        if perm.name == permission_data.name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="权限名称已存在"
            )
    
    permission_dict = {
        "name": permission_data.name,
        "resource": permission_data.resource,
        "action": permission_data.action,
        "description": permission_data.description
    }
    
    created_permission = await rbac_repo.create_permission(permission_dict)
    return created_permission


@router.get("/permissions/{permission_id}", response_model=Permission)
async def get_permission(
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取指定权限信息（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    permission = await rbac_repo.get_permission_by_id(permission_id)
    
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="权限不存在"
        )
    
    return permission


@router.put("/permissions/{permission_id}", response_model=Permission)
async def update_permission(
    permission_id: int,
    permission_data: PermissionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """更新权限（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    permission = await rbac_repo.get_permission_by_id(permission_id)
    
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="权限不存在"
        )
    
    # 更新权限信息
    if permission_data.name is not None:
        permission.name = permission_data.name
    if permission_data.resource is not None:
        permission.resource = permission_data.resource
    if permission_data.action is not None:
        permission.action = permission_data.action
    if permission_data.description is not None:
        permission.description = permission_data.description
    
    # 更新权限
    await db.commit()
    
    # 预加载角色关系，避免 MissingGreenlet 错误
    stmt = select(Permission).options(selectinload(Permission.roles)).where(Permission.id == permission.id)
    result = await db.execute(stmt)
    updated_permission = result.scalar_one()
    return updated_permission


@router.delete("/permissions/{permission_id}")
async def delete_permission(
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """删除权限（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    success = await rbac_repo.delete_permission(permission_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="权限不存在"
        )
    
    return {"message": "权限已删除"}


# 用户角色分配
@router.post("/users/{user_id}/roles/{role_id}")
async def assign_role_to_user(
    user_id: int,
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """为用户分配角色（需要超级用户权限）"""
    rbac_service = RBACService(db)
    success = await rbac_service.grant_role_to_user(user_id, role_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户或角色不存在"
        )
    
    return {"message": "角色已分配给用户"}


@router.delete("/users/{user_id}/roles/{role_id}")
async def revoke_role_from_user(
    user_id: int,
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """从用户撤销角色（需要超级用户权限）"""
    rbac_service = RBACService(db)
    success = await rbac_service.revoke_role_from_user(user_id, role_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户或角色不存在"
        )
    
    return {"message": "角色已从用户撤销"}


# 角色权限分配
@router.post("/roles/{role_id}/permissions/{permission_id}")
async def assign_permission_to_role(
    role_id: int,
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """为角色分配权限（需要超级用户权限）"""
    rbac_service = RBACService(db)
    success = await rbac_service.grant_permission_to_role(role_id, permission_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色或权限不存在"
        )
    
    return {"message": "权限已分配给角色"}


@router.delete("/roles/{role_id}/permissions/{permission_id}")
async def revoke_permission_from_role(
    role_id: int,
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """从角色撤销权限（需要超级用户权限）"""
    rbac_service = RBACService(db)
    success = await rbac_service.revoke_permission_from_role(role_id, permission_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色或权限不存在"
        )
    
    return {"message": "权限已从角色撤销"}


# 权限检查
@router.post("/users/{user_id}/check-permission", response_model=UserPermissionResult)
async def check_user_permission(
    user_id: int,
    permission_check: UserPermissionCheck,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """检查用户是否有特定权限"""
    # 只有超级用户或用户本人才能检查权限
    if not current_user.is_superuser and user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="没有权限检查其他用户的权限"
        )
    
    rbac_service = RBACService(db)
    has_permission = await rbac_service.check_permission(
        user_id, permission_check.resource, permission_check.action
    )
    
    return UserPermissionResult(has_permission=has_permission)