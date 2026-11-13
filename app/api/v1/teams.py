"""团队 API（P3）：建队、邀请、确认、退出。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_client_meta
from app.database import get_db
from app.dependencies_services import get_audit_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.task import (
    InvitationCreate,
    InvitationOut,
    TeamCreate,
    TeamOut,
    TeamUpdate,
)
from app.services.audit_service import AuditService
from app.services.task.team_service import TeamService

router = APIRouter()


def get_team_service(db: AsyncSession = Depends(get_db)) -> TeamService:
    return TeamService(db)


@router.get("", response_model=PaginatedResponse[TeamOut])
async def list_my_teams(
    pagination: PaginationParams = Depends(),
    service: TeamService = Depends(get_team_service),
    current_user: User = Depends(require_permission("team", "read")),
) -> Any:
    items, total = await service.list_my_teams(
        actor=current_user, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(
    body: TeamCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TeamService = Depends(get_team_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("team", "create")),
) -> Any:
    result = await service.create_team(
        actor=current_user, data=body, idempotency_key=idempotency_key
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="team.create",
            resource_type="team",
            resource_id=str(result.get("id")),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"name": body.name, "invitees": body.invitee_user_ids},
            **get_client_meta(request),
        )
    return result


@router.get("/invitations/me", response_model=PaginatedResponse[InvitationOut])
async def list_my_invitations(
    pagination: PaginationParams = Depends(),
    service: TeamService = Depends(get_team_service),
    current_user: User = Depends(require_permission("team", "read")),
) -> Any:
    rows, total = await service.list_pending_invitations(
        actor=current_user, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=rows, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.post("/invitations/{invitation_id}/accept", response_model=dict)
async def accept_invitation(
    invitation_id: int,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TeamService = Depends(get_team_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("team", "read")),
) -> Any:
    result = await service.respond_invitation(
        actor=current_user,
        invitation_id=invitation_id,
        accept=True,
        idempotency_key=idempotency_key,
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="team.invitation.accept",
            resource_type="team_invitation",
            resource_id=str(invitation_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            **get_client_meta(request),
        )
    return result


@router.post("/invitations/{invitation_id}/reject", response_model=dict)
async def reject_invitation(
    invitation_id: int,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TeamService = Depends(get_team_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("team", "read")),
) -> Any:
    result = await service.respond_invitation(
        actor=current_user,
        invitation_id=invitation_id,
        accept=False,
        idempotency_key=idempotency_key,
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="team.invitation.reject",
            resource_type="team_invitation",
            resource_id=str(invitation_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            **get_client_meta(request),
        )
    return result


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(
    team_id: int,
    service: TeamService = Depends(get_team_service),
    current_user: User = Depends(require_permission("team", "read")),
) -> Any:
    return await service.get_team(actor=current_user, team_id=team_id)


@router.patch("/{team_id}", response_model=TeamOut)
async def rename_team(
    team_id: int,
    body: TeamUpdate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TeamService = Depends(get_team_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("team", "manage")),
) -> Any:
    result = await service.rename_team(
        actor=current_user,
        team_id=team_id,
        name=body.name,
        idempotency_key=idempotency_key,
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="team.rename",
            resource_type="team",
            resource_id=str(team_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"name": body.name},
            **get_client_meta(request),
        )
    return result


@router.post("/{team_id}/invitations", response_model=dict, status_code=201)
async def invite_member(
    team_id: int,
    body: InvitationCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TeamService = Depends(get_team_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("team", "manage")),
) -> Any:
    result = await service.invite(
        actor=current_user,
        team_id=team_id,
        data=body,
        idempotency_key=idempotency_key,
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="team.invite",
            resource_type="team",
            resource_id=str(team_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"invitee_user_id": body.invitee_user_id},
            **get_client_meta(request),
        )
    return result


@router.post("/{team_id}/leave", response_model=dict)
async def leave_team(
    team_id: int,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TeamService = Depends(get_team_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("team", "read")),
) -> Any:
    result = await service.leave_team(
        actor=current_user, team_id=team_id, idempotency_key=idempotency_key
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="team.leave",
            resource_type="team",
            resource_id=str(team_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            **get_client_meta(request),
        )
    return result
