"""管理员角色/权限 API（子阶段 2.5）：对齐前端 admin 角色管理 UI。

- GET    /admin/roles                   角色列表（含权限名 + 用户数）
- POST   /admin/roles                   创建角色（key/展示名/描述/权限名）
- PUT    /admin/roles/{role_id}         更新角色元数据
- DELETE /admin/roles/{role_id}         删除角色（系统内置角色禁止）
- PUT    /admin/roles/{role_id}/permissions  全量替换权限（不存在自动创建）
- GET    /admin/permissions             权限点列表
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import NotFoundException
from app.core.request_context import get_client_meta
from app.dependencies_services import get_audit_service, get_rbac_service
from app.middleware.rbac import require_admin_2fa, require_permission
from app.models.user import User
from app.schemas.rbac import (
    AdminPermissionOut,
    AdminRoleCreate,
    AdminRoleOut,
    AdminRolePermissions,
    AdminRoleUpdate,
)
from app.services.audit_service import AuditService
from app.services.rbac.rbac_service import RBACService

router = APIRouter(dependencies=[Depends(require_admin_2fa())])


@router.get("/roles", response_model=list[AdminRoleOut])
async def list_roles(
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("role", "list")),
) -> Any:
    """角色列表（角色 + 权限名 + 用户数）。"""
    return await rbac_service.list_roles_admin()


@router.post("/roles", response_model=AdminRoleOut, status_code=201)
async def create_role(
    body: AdminRoleCreate,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "create")),
) -> Any:
    """创建角色（含权限授予，同一事务）。"""
    role = await rbac_service.create_role_admin(body)
    await audit.record_atomic(
        action="role.create",
        resource_type="role",
        resource_id=str(role.id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"name": role.name, "permissions": body.permissions},
        **get_client_meta(request),
    )
    role_out = next(
        (r for r in await rbac_service.list_roles_admin() if r["id"] == role.id), None
    )
    return role_out or {
        "id": role.id,
        "name": role.name,
        "display_name": role.display_name,
        "description": role.description,
        "is_system": False,
        "is_protected": False,
        "sort_order": 0,
        "permissions": body.permissions,
        "user_count": 0,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }


@router.put("/roles/{role_id}", response_model=AdminRoleOut)
async def update_role(
    role_id: int,
    body: AdminRoleUpdate,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "update")),
) -> Any:
    """更新角色元数据（display_name/description）。"""
    updated = await rbac_service.update_role_admin(role_id, body)
    if updated is None:
        raise NotFoundException(
            message="角色不存在", resource_type="role", resource_id=str(role_id)
        )
    await audit.record_atomic(
        action="role.update",
        resource_type="role",
        resource_id=str(role_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"fields": list(body.model_dump(exclude_unset=True).keys())},
        **get_client_meta(request),
    )
    role_out = next(
        (r for r in await rbac_service.list_roles_admin() if r["id"] == role_id), None
    )
    return role_out or {}


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "delete")),
) -> Any:
    """删除角色（系统内置角色禁止删除）。"""
    success = await rbac_service.delete_role_admin(role_id)
    if not success:
        raise NotFoundException(
            message="角色不存在", resource_type="role", resource_id=str(role_id)
        )
    await audit.record_atomic(
        action="role.delete",
        resource_type="role",
        resource_id=str(role_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        **get_client_meta(request),
    )
    return {"ok": True}


@router.put("/roles/{role_id}/permissions", response_model=AdminRoleOut)
async def replace_permissions(
    role_id: int,
    body: AdminRolePermissions,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "manage_permissions")),
) -> Any:
    """全量替换角色权限（权限名 resource:action，不存在自动创建）。"""
    updated = await rbac_service.replace_role_permissions(role_id, body.permissions)
    if updated is None:
        raise NotFoundException(
            message="角色不存在", resource_type="role", resource_id=str(role_id)
        )
    await audit.record_atomic(
        action="role.replace_permissions",
        resource_type="role",
        resource_id=str(role_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"permissions": body.permissions},
        **get_client_meta(request),
    )
    role_out = next(
        (r for r in await rbac_service.list_roles_admin() if r["id"] == role_id), None
    )
    return role_out or {}


@router.get("/permissions", response_model=list[AdminPermissionOut])
async def list_permissions(
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("permission", "list")),
) -> Any:
    """权限点列表（全部）。"""
    return await rbac_service.list_permissions_admin()
