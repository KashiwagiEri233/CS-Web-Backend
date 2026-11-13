"""RBAC 权限目录只读路由。

P7：运行时创建/修改/删除权限的入口已移除；权限目录唯一事实源为
``rbac_seed_data.py``，角色权限分配统一走 ``PUT /admin/roles/{id}/permissions``。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundException
from app.dependencies_services import get_rbac_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.rbac import Permission
from app.services.rbac.rbac_service import RBACService

router = APIRouter()


@router.get("/permissions", response_model=PaginatedResponse[Permission])
async def get_permissions(
    pagination: PaginationParams = Depends(),
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("permission", "list")),
) -> Any:
    """获取权限列表（需要 permission:list，分页）。"""
    permissions = await rbac_service.get_all_permissions(
        skip=pagination.skip, limit=pagination.limit
    )
    total = await rbac_service.count_permissions()
    return PaginatedResponse(
        items=permissions, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/permissions/{permission_id}", response_model=Permission)
async def get_permission(
    permission_id: int,
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("permission", "read")),
) -> Any:
    """获取指定权限（需要 permission:read）。"""
    permission = await rbac_service.get_permission(permission_id)
    if not permission:
        raise NotFoundException(
            message="权限不存在",
            resource_type="permission",
            resource_id=permission_id,
        )
    return permission
