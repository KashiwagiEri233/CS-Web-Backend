"""团队编排（P3）：建队、邀请、加入、退出。"""

from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.timezone import now_utc
from app.models.user import User
from app.repositories.team_repo import TeamRepository
from app.schemas.task import InvitationCreate, TeamCreate
from app.services.task.access import require_active_member, team_to_dict
from app.services.wallet.idempotency_service import (
    IdempotencyService,
    require_idempotency_key,
)

_OP_TEAM_CREATE = "team_create"
_OP_TEAM_RENAME = "team_rename"
_OP_TEAM_INVITE = "team_invite"
_OP_TEAM_RESPOND = "team_invitation_respond"
_OP_TEAM_LEAVE = "team_leave"


class TeamService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TeamRepository(db)
        self.idem = IdempotencyService(db)

    async def _begin(self, *, actor_id: int, operation: str, key: Optional[str], payload: dict):
        key = require_idempotency_key(key)
        replay = await self.idem.replay(
            actor_id=actor_id, operation=operation, key=key, payload=payload
        )
        return key, replay

    async def _save(self, *, actor_id, operation, key, payload, response) -> dict:
        await self.idem.save(
            actor_id=actor_id,
            operation=operation,
            key=key,
            payload=payload,
            response=response,
        )
        return response

    async def _serialize(self, team) -> dict:
        members = await self.repo.list_active_members(team.id)
        return team_to_dict(team, members)

    async def _get_team(self, team_id: int):
        team = await self.repo.get_team(team_id)
        if team is None or team.status == "archived":
            raise NotFoundException(
                message="队伍不存在", resource_type="team", resource_id=str(team_id)
            )
        return team

    async def _ensure_member_or_captain(self, team, user_id: int) -> None:
        if team.captain_user_id == user_id:
            return
        if await self.repo.get_active_member(team.id, user_id) is None:
            raise AuthorizationException(
                message="无权查看该队伍",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )

    async def create_team(
        self,
        *,
        actor: User,
        data: TeamCreate,
        idempotency_key: Optional[str],
    ) -> dict:
        payload = {"name": data.name, "invitee_user_ids": data.invitee_user_ids}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_TEAM_CREATE, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        await require_active_member(self.db, actor.id)
        team = await self.repo.create_team(
            {"name": data.name, "captain_user_id": actor.id, "status": "forming"}
        )
        await self.repo.add_member(team.id, actor.id, "captain")
        expires_at = now_utc() + timedelta(hours=settings.TEAM_INVITATION_TTL_HOURS)
        for invitee_id in dict.fromkeys(data.invitee_user_ids):
            if invitee_id == actor.id:
                continue
            await self._create_invitation(
                team_id=team.id,
                inviter_id=actor.id,
                invitee_id=invitee_id,
                expires_at=expires_at,
            )
        response = await self._serialize(team)
        return await self._save(
            actor_id=actor.id,
            operation=_OP_TEAM_CREATE,
            key=key,
            payload=payload,
            response=response,
        )

    async def rename_team(
        self,
        *,
        actor: User,
        team_id: int,
        name: str,
        idempotency_key: Optional[str],
    ) -> dict:
        payload = {"team_id": team_id, "name": name}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_TEAM_RENAME, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        team = await self.repo.get_team_for_update(team_id)
        if team is None or team.status == "archived":
            raise NotFoundException(
                message="队伍不存在", resource_type="team", resource_id=str(team_id)
            )
        if team.captain_user_id != actor.id:
            raise AuthorizationException(
                message="只有队长可以修改队伍",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        await self.repo.update_team(
            team, {"name": name, "version": team.version + 1}
        )
        response = await self._serialize(team)
        return await self._save(
            actor_id=actor.id,
            operation=_OP_TEAM_RENAME,
            key=key,
            payload=payload,
            response=response,
        )

    async def _create_invitation(
        self, *, team_id: int, inviter_id: int, invitee_id: int, expires_at
    ) -> None:
        if await self.repo.get_active_member(team_id, invitee_id) is not None:
            raise ValidationException(message="该用户已在队伍中")
        await require_active_member(self.db, invitee_id)
        if await self.repo.get_pending_invitation(team_id, invitee_id) is not None:
            return
        await self.repo.create_invitation(
            {
                "team_id": team_id,
                "invitee_user_id": invitee_id,
                "inviter_user_id": inviter_id,
                "status": "pending",
                "expires_at": expires_at,
            }
        )

    async def invite(
        self,
        *,
        actor: User,
        team_id: int,
        data: InvitationCreate,
        idempotency_key: Optional[str],
    ) -> dict:
        payload = {"team_id": team_id, "invitee_user_id": data.invitee_user_id}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_TEAM_INVITE, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        team = await self.repo.get_team_for_update(team_id)
        if team is None or team.status == "archived":
            raise NotFoundException(
                message="队伍不存在", resource_type="team", resource_id=str(team_id)
            )
        if team.captain_user_id != actor.id:
            raise AuthorizationException(
                message="只有队长可以邀请成员",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        if await self.repo.team_has_open_claim(team.id):
            raise ConflictException(
                message="执行中的队伍名单已锁定",
                error_code=ErrorCode.Conflict.TEAM_ROSTER_LOCKED,
            )
        members = await self.repo.count_active_members(team.id)
        if members >= settings.TASK_TEAM_MAX_MEMBERS:
            raise ValidationException(
                message="队伍人数已达配置上限",
                error_code=ErrorCode.Validation.INVALID_TEAM_SIZE,
            )
        await self._create_invitation(
            team_id=team.id,
            inviter_id=actor.id,
            invitee_id=data.invitee_user_id,
            expires_at=now_utc()
            + timedelta(hours=settings.TEAM_INVITATION_TTL_HOURS),
        )
        invitation = await self.repo.get_pending_invitation(team.id, data.invitee_user_id)
        response = {
            "id": invitation.id if invitation else None,
            "team_id": team.id,
            "invitee_user_id": data.invitee_user_id,
            "inviter_user_id": actor.id,
            "status": invitation.status if invitation else "pending",
            "expires_at": invitation.expires_at if invitation else None,
        }
        return await self._save(
            actor_id=actor.id,
            operation=_OP_TEAM_INVITE,
            key=key,
            payload=payload,
            response=response,
        )

    async def respond_invitation(
        self,
        *,
        actor: User,
        invitation_id: int,
        accept: bool,
        idempotency_key: Optional[str],
    ) -> dict:
        payload = {"invitation_id": invitation_id, "accept": accept}
        key, replay = await self._begin(
            actor_id=actor.id,
            operation=_OP_TEAM_RESPOND,
            key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        invitation = await self.repo.get_invitation_for_update(invitation_id)
        if invitation is None:
            raise NotFoundException(
                message="邀请不存在",
                resource_type="team_invitation",
                resource_id=str(invitation_id),
            )
        if invitation.invitee_user_id != actor.id:
            raise AuthorizationException(
                message="只有受邀者本人可以确认邀请",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        if invitation.status != "pending":
            raise ConflictException(
                message="邀请已处理或已失效",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        if invitation.expires_at <= now_utc():
            await self.repo.update_invitation(
                invitation,
                {"status": "expired", "responded_at": now_utc()},
            )
            raise ConflictException(
                message="邀请已过期",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        team = await self.repo.get_team_for_update(invitation.team_id)
        if team is None or team.status == "archived":
            raise NotFoundException(
                message="队伍不存在", resource_type="team", resource_id=str(invitation.team_id)
            )
        if not accept:
            await self.repo.update_invitation(
                invitation,
                {"status": "rejected", "responded_at": now_utc()},
            )
            response = {"invitation_id": invitation.id, "status": invitation.status}
            return await self._save(
                actor_id=actor.id,
                operation=_OP_TEAM_RESPOND,
                key=key,
                payload=payload,
                response=response,
            )
        if await self.repo.team_has_open_claim(team.id):
            raise ConflictException(
                message="执行中的队伍名单已锁定",
                error_code=ErrorCode.Conflict.TEAM_ROSTER_LOCKED,
            )
        existing = await self.repo.get_member_any(team.id, actor.id)
        if existing is not None and existing.status == "active":
            raise ConflictException(message="你已在队伍中")
        if await self.repo.count_active_members(team.id) >= settings.TASK_TEAM_MAX_MEMBERS:
            raise ValidationException(
                message="队伍人数已达配置上限",
                error_code=ErrorCode.Validation.INVALID_TEAM_SIZE,
            )
        if existing is not None:
            await self.repo.reactivate_member(existing, "member")
        else:
            await self.repo.add_member(team.id, actor.id, "member")
        await self.repo.update_invitation(
            invitation,
            {"status": "accepted", "responded_at": now_utc()},
        )
        response = {"invitation_id": invitation.id, "status": invitation.status}
        return await self._save(
            actor_id=actor.id,
            operation=_OP_TEAM_RESPOND,
            key=key,
            payload=payload,
            response=response,
        )

    async def leave_team(
        self,
        *,
        actor: User,
        team_id: int,
        idempotency_key: Optional[str],
    ) -> dict:
        payload = {"team_id": team_id}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_TEAM_LEAVE, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        team = await self.repo.get_team_for_update(team_id)
        if team is None or team.status == "archived":
            raise NotFoundException(
                message="队伍不存在", resource_type="team", resource_id=str(team_id)
            )
        if team.captain_user_id == actor.id:
            raise ConflictException(
                message="队长不能直接退出，请先解散或转让队伍",
                error_code=ErrorCode.Conflict.TEAM_ROSTER_LOCKED,
            )
        if await self.repo.team_has_open_claim(team.id):
            raise ConflictException(
                message="执行中的队伍名单已锁定",
                error_code=ErrorCode.Conflict.TEAM_ROSTER_LOCKED,
            )
        if await self.repo.get_active_member(team.id, actor.id) is None:
            raise ConflictException(message="你不在该队伍中")
        await self.repo.leave_member(team.id, actor.id, now_utc())
        response = {"team_id": team.id, "user_id": actor.id, "status": "left"}
        return await self._save(
            actor_id=actor.id,
            operation=_OP_TEAM_LEAVE,
            key=key,
            payload=payload,
            response=response,
        )

    async def list_my_teams(
        self, *, actor: User, skip: int = 0, limit: int = 20
    ) -> tuple[List[dict], int]:
        teams = await self.repo.list_teams_for_user(actor.id, skip=skip, limit=limit)
        items = [await self._serialize(team) for team in teams]
        total = await self.repo.count_teams_for_user(actor.id)
        return items, total

    async def get_team(self, *, actor: User, team_id: int) -> dict:
        team = await self._get_team(team_id)
        await self._ensure_member_or_captain(team, actor.id)
        return await self._serialize(team)

    async def list_pending_invitations(
        self, *, actor: User, skip: int = 0, limit: int = 20
    ) -> tuple[list, int]:
        rows = await self.repo.list_pending_invitations(
            actor.id, skip=skip, limit=limit
        )
        total = await self.repo.count_pending_invitations(actor.id)
        return rows, total
