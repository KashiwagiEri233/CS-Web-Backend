"""RBAC 查询与权限检查路由（只读 + check）。"""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundException, PermissionDeniedException
from app.dependencies import get_current_active_user
from app.dependencies_services import get_rbac_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.rbac import (
    Role,
    UserPermissionCheck,
    UserPermissionResult,
    UserPermissionsResponse,
)
from app.services.rbac_service import RBACService

router = APIRouter()


@router.post("/users/{user_id}/check-permission", response_model=UserPermissionResult)
async def check_user_permission(
    user_id: int,
    permission_check: UserPermissionCheck,
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """检查用户是否有特定权限（本人或超级用户）。"""
    if not current_user.is_superuser and user_id != current_user.id:
        raise PermissionDeniedException(
            required_permissions=["check_permission"],
        )

    has_permission = await rbac_service.check_permission(
        user_id, permission_check.resource, permission_check.action
    )
    return UserPermissionResult(has_permission=has_permission)


@router.get("/me/permissions", response_model=UserPermissionsResponse)
async def get_my_permissions(
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前登录用户的权限集合。"""
    if current_user.is_superuser:
        permissions = {"*:*"}
    else:
        permissions = await rbac_service.get_user_permissions(current_user.id)
    return UserPermissionsResponse(
        user_id=current_user.id, permissions=sorted(permissions)
    )


@router.get("/me/roles", response_model=List[Role])
async def get_my_roles(
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前登录用户的角色列表。"""
    return await rbac_service.get_user_roles(current_user.id)


@router.get("/users/{user_id}/permissions", response_model=UserPermissionsResponse)
async def get_user_permissions(
    user_id: int,
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("user", "read")),
) -> Any:
    """获取指定用户的权限集合（需要 user:read）。"""
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
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("user", "read")),
) -> Any:
    """获取指定用户的角色列表（需要 user:read）。"""
    if not await rbac_service.user_exists(user_id):
        raise NotFoundException(
            message="用户不存在",
            resource_type="user",
            resource_id=user_id,
        )
    return await rbac_service.get_user_roles(user_id)
