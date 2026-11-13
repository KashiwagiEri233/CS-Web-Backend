"""RBAC 角色只读路由。

P7：运行时角色 CRUD 统一收敛到 ``/admin/roles``（含双显示名、保护策略、
If-Match 与审计）；``/rbac`` 仅保留只读兼容查询。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundException
from app.dependencies_services import get_rbac_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.rbac import Role
from app.services.rbac.rbac_service import RBACService

router = APIRouter()


@router.get("/roles", response_model=PaginatedResponse[Role])
async def get_roles(
    pagination: PaginationParams = Depends(),
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("role", "list")),
) -> Any:
    """获取角色列表（需要 role:list，分页）。"""
    roles = await rbac_service.get_all_roles(
        skip=pagination.skip, limit=pagination.limit
    )
    total = await rbac_service.count_roles()
    return PaginatedResponse(
        items=roles, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/roles/{role_id}", response_model=Role)
async def get_role(
    role_id: int,
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("role", "read")),
) -> Any:
    """获取指定角色（需要 role:read）。"""
    role = await rbac_service.get_role(role_id)
    if not role:
        raise NotFoundException(
            message="角色不存在",
            resource_type="role",
            resource_id=role_id,
        )
    return role
