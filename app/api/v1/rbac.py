from typing import Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    PermissionDeniedException,
)
from app.database import get_db
from app.dependencies import get_current_active_user, get_current_superuser
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.rbac import (
    Role, RoleCreate, RoleUpdate,
    Permission, PermissionCreate, PermissionUpdate,
    UserPermissionCheck, UserPermissionResult,
    UserPermissionsResponse,
)
from app.services.rbac_service import RBACService

router = APIRouter()


# 角色管理
@router.get("/roles", response_model=PaginatedResponse[Role])
async def get_roles(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取角色列表（需要超级用户权限，分页）"""
    rbac_service = RBACService(db)
    roles = await rbac_service.get_all_roles(skip=pagination.skip, limit=pagination.limit)
    total = await rbac_service.count_roles()
    return PaginatedResponse(
        items=roles, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.post("/roles", response_model=Role)
async def create_role(
    role_data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """创建角色（需要超级用户权限）"""
    rbac_service = RBACService(db)

    # 按名称查重（避免全表遍历）
    if await rbac_service.get_role_by_name(role_data.name):
        raise ConflictException(
            message="角色名称已存在",
            details={"name": role_data.name},
        )

    role_dict = {
        "name": role_data.name,
        "description": role_data.description,
        "is_active": role_data.is_active
    }
    return await rbac_service.create_role(role_dict)


@router.get("/roles/{role_id}", response_model=Role)
async def get_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取指定角色信息（需要超级用户权限）"""
    rbac_service = RBACService(db)
    role = await rbac_service.get_role(role_id)

    if not role:
        raise NotFoundException(
            message="角色不存在",
            resource_type="role",
            resource_id=role_id,
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
    rbac_service = RBACService(db)
    updated_role = await rbac_service.update_role(role_id, role_data.model_dump(exclude_unset=True))

    if updated_role is None:
        raise NotFoundException(
            message="角色不存在",
            resource_type="role",
            resource_id=role_id,
        )

    return updated_role


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """删除角色（需要超级用户权限）"""
    rbac_service = RBACService(db)
    success = await rbac_service.delete_role(role_id)

    if not success:
        raise NotFoundException(
            message="角色不存在",
            resource_type="role",
            resource_id=role_id,
        )

    return {"message": "角色已删除"}


# 权限管理
@router.get("/permissions", response_model=PaginatedResponse[Permission])
async def get_permissions(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取权限列表（需要超级用户权限，分页）"""
    rbac_service = RBACService(db)
    permissions = await rbac_service.get_all_permissions(
        skip=pagination.skip, limit=pagination.limit
    )
    total = await rbac_service.count_permissions()
    return PaginatedResponse(
        items=permissions, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.post("/permissions", response_model=Permission)
async def create_permission(
    permission_data: PermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """创建权限（需要超级用户权限）"""
    rbac_service = RBACService(db)

    # 按名称查重（避免全表遍历）
    if await rbac_service.get_permission_by_name(permission_data.name):
        raise ConflictException(
            message="权限名称已存在",
            details={"name": permission_data.name},
        )

    permission_dict = {
        "name": permission_data.name,
        "resource": permission_data.resource,
        "action": permission_data.action,
        "description": permission_data.description
    }
    return await rbac_service.create_permission(permission_dict)


@router.get("/permissions/{permission_id}", response_model=Permission)
async def get_permission(
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取指定权限信息（需要超级用户权限）"""
    rbac_service = RBACService(db)
    permission = await rbac_service.get_permission(permission_id)

    if not permission:
        raise NotFoundException(
            message="权限不存在",
            resource_type="permission",
            resource_id=permission_id,
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
    rbac_service = RBACService(db)
    updated_permission = await rbac_service.update_permission(
        permission_id, permission_data.model_dump(exclude_unset=True)
    )

    if updated_permission is None:
        raise NotFoundException(
            message="权限不存在",
            resource_type="permission",
            resource_id=permission_id,
        )

    return updated_permission


@router.delete("/permissions/{permission_id}")
async def delete_permission(
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """删除权限（需要超级用户权限）"""
    rbac_service = RBACService(db)
    success = await rbac_service.delete_permission(permission_id)

    if not success:
        raise NotFoundException(
            message="权限不存在",
            resource_type="permission",
            resource_id=permission_id,
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
        raise NotFoundException(
            message="用户或角色不存在",
            resource_type="user/role",
            resource_id=f"{user_id}/{role_id}",
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
        raise NotFoundException(
            message="用户或角色不存在",
            resource_type="user/role",
            resource_id=f"{user_id}/{role_id}",
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
        raise NotFoundException(
            message="角色或权限不存在",
            resource_type="role/permission",
            resource_id=f"{role_id}/{permission_id}",
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
        raise NotFoundException(
            message="角色或权限不存在",
            resource_type="role/permission",
            resource_id=f"{role_id}/{permission_id}",
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
    if not current_user.is_superuser and user_id != current_user.id:
        raise PermissionDeniedException(
            required_permissions=["check_permission"],
        )

    rbac_service = RBACService(db)
    has_permission = await rbac_service.check_permission(
        user_id, permission_check.resource, permission_check.action
    )

    return UserPermissionResult(has_permission=has_permission)


# 用户授权查询（只读）
@router.get("/me/permissions", response_model=UserPermissionsResponse)
async def get_my_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前登录用户的权限集合"""
    rbac_service = RBACService(db)
    # 超级用户视为拥有全部权限，这里以通配符表示
    if current_user.is_superuser:
        permissions = {"*:*"}
    else:
        permissions = await rbac_service.get_user_permissions(current_user.id)
    return UserPermissionsResponse(user_id=current_user.id, permissions=sorted(permissions))


@router.get("/me/roles", response_model=List[Role])
async def get_my_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前登录用户的角色列表"""
    rbac_service = RBACService(db)
    return await rbac_service.get_user_roles(current_user.id)


@router.get("/users/{user_id}/permissions", response_model=UserPermissionsResponse)
async def get_user_permissions(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """获取指定用户的权限集合（需要超级用户权限）"""
    rbac_service = RBACService(db)
    if not await rbac_service.user_exists(user_id):
        raise NotFoundException(
            message="用户不存在",
            resource_type="user",
            resource_id=user_id,
        )
    permissions = await rbac_service.get_user_permissions(user_id)
    return UserPermissionsResponse(user_id=user_id, permissions=sorted(permissions))


@router.get("/users/{user_id}/roles", response_model=List[Role])
async def get_user_roles(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """获取指定用户的角色列表（需要超级用户权限）"""
    rbac_service = RBACService(db)
    if not await rbac_service.user_exists(user_id):
        raise NotFoundException(
            message="用户不存在",
            resource_type="user",
            resource_id=user_id,
        )
    return await rbac_service.get_user_roles(user_id)