"""RBAC 角色 CRUD 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import ConflictException, NotFoundException
from app.core.request_context import get_client_meta
from app.dependencies_services import get_audit_service, get_rbac_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.rbac import Role, RoleCreate, RoleUpdate
from app.services.audit_service import AuditService
from app.services.rbac_service import RBACService

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


@router.post("/roles", response_model=Role)
async def create_role(
    role_data: RoleCreate,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "create")),
) -> Any:
    """创建角色（需要 role:create）。"""
    if await rbac_service.get_role_by_name(role_data.name):
        raise ConflictException(
            message="角色名称已存在",
            details={"name": role_data.name},
        )

    role = await rbac_service.create_role(
        {
            "name": role_data.name,
            "description": role_data.description,
            "is_active": role_data.is_active,
        },
        commit=False,
    )
    await audit.record_atomic(
        action="role.create",
        resource_type="role",
        resource_id=str(role.id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"name": role.name},
        **get_client_meta(request),
    )
    return role


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


@router.put("/roles/{role_id}", response_model=Role)
async def update_role(
    role_id: int,
    role_data: RoleUpdate,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "update")),
) -> Any:
    """更新角色（需要 role:update）。"""
    updated = await rbac_service.update_role(
        role_id, role_data.model_dump(exclude_unset=True), commit=False
    )
    if updated is None:
        raise NotFoundException(
            message="角色不存在",
            resource_type="role",
            resource_id=role_id,
        )
    await audit.record_atomic(
        action="role.update",
        resource_type="role",
        resource_id=str(role_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"fields": list(role_data.model_dump(exclude_unset=True).keys())},
        **get_client_meta(request),
    )
    return updated


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "delete")),
) -> Any:
    """删除角色（需要 role:delete）。"""
    success = await rbac_service.delete_role(role_id, commit=False)
    if not success:
        raise NotFoundException(
            message="角色不存在",
            resource_type="role",
            resource_id=role_id,
        )
    await audit.record_atomic(
        action="role.delete",
        resource_type="role",
        resource_id=str(role_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        **get_client_meta(request),
    )
    return {"message": "角色已删除"}
