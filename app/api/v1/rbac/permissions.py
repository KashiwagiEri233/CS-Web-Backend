"""RBAC 权限 CRUD 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import ConflictException, NotFoundException
from app.core.request_context import get_client_meta
from app.dependencies_services import get_audit_service, get_rbac_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.rbac import Permission, PermissionCreate, PermissionUpdate
from app.services.audit_service import AuditService
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


@router.post("/permissions", response_model=Permission)
async def create_permission(
    permission_data: PermissionCreate,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("permission", "create")),
) -> Any:
    """创建权限（需要 permission:create）。"""
    if await rbac_service.get_permission_by_name(permission_data.name):
        raise ConflictException(
            message="权限名称已存在",
            details={"name": permission_data.name},
        )
    if await rbac_service.get_permission_by_resource_action(
        permission_data.resource, permission_data.action
    ):
        raise ConflictException(
            message="该资源的操作权限已存在",
            details={
                "resource": permission_data.resource,
                "action": permission_data.action,
            },
        )

    permission = await rbac_service.create_permission(
        {
            "name": permission_data.name,
            "resource": permission_data.resource,
            "action": permission_data.action,
            "description": permission_data.description,
        },
        commit=False,
    )
    await audit.record_atomic(
        action="permission.create",
        resource_type="permission",
        resource_id=str(permission.id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"name": permission.name},
        **get_client_meta(request),
    )
    return permission


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


@router.put("/permissions/{permission_id}", response_model=Permission)
async def update_permission(
    permission_id: int,
    permission_data: PermissionUpdate,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("permission", "update")),
) -> Any:
    """更新权限（需要 permission:update）。"""
    updated = await rbac_service.update_permission(
        permission_id,
        permission_data.model_dump(exclude_unset=True),
        commit=False,
    )
    if updated is None:
        raise NotFoundException(
            message="权限不存在",
            resource_type="permission",
            resource_id=permission_id,
        )
    await audit.record_atomic(
        action="permission.update",
        resource_type="permission",
        resource_id=str(permission_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"fields": list(permission_data.model_dump(exclude_unset=True).keys())},
        **get_client_meta(request),
    )
    return updated


@router.delete("/permissions/{permission_id}")
async def delete_permission(
    permission_id: int,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("permission", "delete")),
) -> Any:
    """删除权限（需要 permission:delete）。"""
    success = await rbac_service.delete_permission(permission_id, commit=False)
    if not success:
        raise NotFoundException(
            message="权限不存在",
            resource_type="permission",
            resource_id=permission_id,
        )
    await audit.record_atomic(
        action="permission.delete",
        resource_type="permission",
        resource_id=str(permission_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        **get_client_meta(request),
    )
    return {"message": "权限已删除"}
