"""组织 API：本人组织信息、峰与成员查询、管理员峰/成员管理。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_client_meta
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_audit_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.audit import AuditLogItem
from app.schemas.organization import (
    MemberCreate,
    MemberMove,
    MemberOut,
    MemberUpdate,
    OrganizationMeOut,
    PeakCreate,
    PeakOut,
    PeakUpdate,
)
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.services.audit_service import AuditService
from app.services.organization.organization_service import OrganizationService

router = APIRouter()
admin_router = APIRouter()


def get_organization_service(
    db: AsyncSession = Depends(get_db),
) -> OrganizationService:
    return OrganizationService(db)


@router.get("/me", response_model=OrganizationMeOut)
async def get_my_organization(
    service: OrganizationService = Depends(get_organization_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """本人组织信息：成员档案 + 角色绑定 + 授权版本。"""
    return await service.get_me(current_user.id)


@router.get("/peaks", response_model=PaginatedResponse[PeakOut])
async def list_peaks(
    pagination: PaginationParams = Depends(),
    include_inactive: bool = Query(False),
    service: OrganizationService = Depends(get_organization_service),
    current_user: User = Depends(require_permission("peak", "read")),
) -> Any:
    peaks = await service.list_peaks(
        active_only=not include_inactive, skip=pagination.skip, limit=pagination.limit
    )
    total = await service.count_peaks(active_only=not include_inactive)
    return PaginatedResponse(
        items=peaks, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/members", response_model=PaginatedResponse[MemberOut])
async def list_members(
    pagination: PaginationParams = Depends(),
    q: Optional[str] = Query(None, max_length=50),
    peak_id: Optional[int] = Query(None, gt=0),
    membership_status: Optional[str] = None,
    service: OrganizationService = Depends(get_organization_service),
    current_user: User = Depends(require_permission("member", "read")),
) -> Any:
    rows, total = await service.list_members(
        current_user,
        keyword=q,
        peak_id=peak_id,
        membership_status=membership_status,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=rows, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/members/{member_id}", response_model=MemberOut)
async def get_member(
    member_id: int,
    service: OrganizationService = Depends(get_organization_service),
    current_user: User = Depends(require_permission("member", "read")),
) -> Any:
    return await service.get_member(current_user, member_id)


# ------------------------------------------------------------------ 管理端


@admin_router.post("/peaks", response_model=PeakOut, status_code=201)
async def create_peak(
    body: PeakCreate,
    request: Request,
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("peak", "create")),
) -> Any:
    peak = await service.create_peak(body.model_dump())
    await audit.record_atomic(
        action="organization.peak.create",
        resource_type="peak",
        resource_id=str(peak.id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"code": peak.code, "name": peak.name},
        **get_client_meta(request),
    )
    return peak


@admin_router.patch("/peaks/{peak_id}", response_model=PeakOut)
async def update_peak(
    peak_id: int,
    body: PeakUpdate,
    request: Request,
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("peak", "update")),
) -> Any:
    peak = await service.update_peak(
        peak_id, body.model_dump(exclude_unset=True)
    )
    await audit.record_atomic(
        action="organization.peak.update",
        resource_type="peak",
        resource_id=str(peak_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"fields": list(body.model_dump(exclude_unset=True).keys())},
        **get_client_meta(request),
    )
    return peak


@admin_router.post("/peaks/{peak_id}/archive", response_model=PeakOut)
async def archive_peak(
    peak_id: int,
    request: Request,
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("peak", "archive")),
) -> Any:
    peak = await service.archive_peak(peak_id)
    await audit.record_atomic(
        action="organization.peak.archive",
        resource_type="peak",
        resource_id=str(peak_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        **get_client_meta(request),
    )
    return peak


@admin_router.get("/members", response_model=PaginatedResponse[MemberOut])
async def admin_list_members(
    pagination: PaginationParams = Depends(),
    q: Optional[str] = Query(None, max_length=50),
    peak_id: Optional[int] = Query(None, gt=0),
    membership_status: Optional[str] = None,
    service: OrganizationService = Depends(get_organization_service),
    current_user: User = Depends(require_permission("member", "read")),
) -> Any:
    rows, total = await service.list_members(
        current_user,
        keyword=q,
        peak_id=peak_id,
        membership_status=membership_status,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=rows, total=total, skip=pagination.skip, limit=pagination.limit
    )


@admin_router.get(
    "/members/{member_id}/history", response_model=PaginatedResponse[AuditLogItem]
)
async def member_history(
    member_id: int,
    pagination: PaginationParams = Depends(),
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("audit", "read")),
) -> Any:
    """成员历史：成员范围校验 + audit:read，返回脱敏审计条目。"""
    await service.get_member(current_user, member_id)
    rows, total = await audit.list_logs(
        skip=pagination.skip,
        limit=pagination.limit,
        resource_type="member",
        resource_id=str(member_id),
    )
    items = [AuditLogItem.model_validate(audit.to_item_dict(row)) for row in rows]
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@admin_router.get("/history", response_model=PaginatedResponse[AuditLogItem])
async def organization_history(
    pagination: PaginationParams = Depends(),
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("audit", "read")),
) -> Any:
    """组织历史：仅全范围账号可读（峰范围无法安全还原跨峰历史）。"""
    await service.require_global_scope(current_user)
    rows, total = await audit.list_logs(
        skip=pagination.skip,
        limit=pagination.limit,
        resource_type="member",
    )
    items = [AuditLogItem.model_validate(audit.to_item_dict(row)) for row in rows]
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@admin_router.post("/members", response_model=MemberOut, status_code=201)
async def create_member(
    body: MemberCreate,
    request: Request,
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("member", "approve")),
) -> Any:
    member = await service.create_member(
        current_user,
        user_id=body.user_id,
        peak_id=body.peak_id,
        student_id=body.student_id,
    )
    await audit.record_atomic(
        action="organization.member.create",
        resource_type="member",
        resource_id=str(member["id"]),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"user_id": body.user_id, "peak_id": body.peak_id},
        **get_client_meta(request),
    )
    return member


@admin_router.patch("/members/{member_id}", response_model=MemberOut)
async def update_member(
    member_id: int,
    body: MemberUpdate,
    request: Request,
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("member", "update")),
) -> Any:
    member = await service.update_member(
        current_user, member_id, body.model_dump(exclude_unset=True)
    )
    await audit.record_atomic(
        action="organization.member.update",
        resource_type="member",
        resource_id=str(member_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"fields": list(body.model_dump(exclude_unset=True).keys())},
        **get_client_meta(request),
    )
    return member


@admin_router.post("/members/{member_id}/move", response_model=MemberOut)
async def move_member(
    member_id: int,
    body: MemberMove,
    request: Request,
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("member", "move")),
) -> Any:
    member = await service.move_member(current_user, member_id, body.peak_id)
    await audit.record_atomic(
        action="organization.member.move",
        resource_type="member",
        resource_id=str(member_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"peak_id": body.peak_id},
        **get_client_meta(request),
    )
    return member


@admin_router.post("/members/{member_id}/remove", response_model=MemberOut)
async def remove_member(
    member_id: int,
    request: Request,
    service: OrganizationService = Depends(get_organization_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("member", "remove")),
) -> Any:
    member = await service.remove_member(current_user, member_id)
    await audit.record_atomic(
        action="organization.member.remove",
        resource_type="member",
        resource_id=str(member_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"user_id": member["user_id"]},
        **get_client_meta(request),
    )
    return member
