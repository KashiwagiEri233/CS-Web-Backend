"""RBAC 分配路由：用户↔角色、角色↔权限。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import NotFoundException
from app.core.request_context import get_client_meta
from app.dependencies_services import get_audit_service, get_rbac_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.rbac_service import RBACService

router = APIRouter()


@router.post("/users/{user_id}/roles/{role_id}")
async def assign_role_to_user(
    user_id: int,
    role_id: int,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("user", "manage_roles")),
) -> Any:
    """为用户分配角色（需要 user:manage_roles）。"""
    success = await rbac_service.grant_role_to_user(user_id, role_id, commit=False)
    if not success:
        raise NotFoundException(
            message="用户或角色不存在",
            resource_type="user/role",
            resource_id=f"{user_id}/{role_id}",
        )
    await audit.record_atomic(
        action="user.grant_role",
        resource_type="user",
        resource_id=str(user_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"role_id": role_id},
        **get_client_meta(request),
    )
    return {"message": "角色已分配给用户"}


@router.delete("/users/{user_id}/roles/{role_id}")
async def revoke_role_from_user(
    user_id: int,
    role_id: int,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("user", "manage_roles")),
) -> Any:
    """从用户撤销角色（需要 user:manage_roles）。"""
    success = await rbac_service.revoke_role_from_user(user_id, role_id, commit=False)
    if not success:
        raise NotFoundException(
            message="用户或角色不存在",
            resource_type="user/role",
            resource_id=f"{user_id}/{role_id}",
        )
    await audit.record_atomic(
        action="user.revoke_role",
        resource_type="user",
        resource_id=str(user_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"role_id": role_id},
        **get_client_meta(request),
    )
    return {"message": "角色已从用户撤销"}


@router.post("/roles/{role_id}/permissions/{permission_id}")
async def assign_permission_to_role(
    role_id: int,
    permission_id: int,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "manage_permissions")),
) -> Any:
    """为角色分配权限（需要 role:manage_permissions）。"""
    success = await rbac_service.grant_permission_to_role(
        role_id, permission_id, commit=False
    )
    if not success:
        raise NotFoundException(
            message="角色或权限不存在",
            resource_type="role/permission",
            resource_id=f"{role_id}/{permission_id}",
        )
    await audit.record_atomic(
        action="role.grant_permission",
        resource_type="role",
        resource_id=str(role_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"permission_id": permission_id},
        **get_client_meta(request),
    )
    return {"message": "权限已分配给角色"}


@router.delete("/roles/{role_id}/permissions/{permission_id}")
async def revoke_permission_from_role(
    role_id: int,
    permission_id: int,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("role", "manage_permissions")),
) -> Any:
    """从角色撤销权限（需要 role:manage_permissions）。"""
    success = await rbac_service.revoke_permission_from_role(
        role_id, permission_id, commit=False
    )
    if not success:
        raise NotFoundException(
            message="角色或权限不存在",
            resource_type="role/permission",
            resource_id=f"{role_id}/{permission_id}",
        )
    await audit.record_atomic(
        action="role.revoke_permission",
        resource_type="role",
        resource_id=str(role_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"permission_id": permission_id},
        **get_client_meta(request),
    )
    return {"message": "权限已从角色撤销"}
