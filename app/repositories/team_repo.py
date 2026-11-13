"""团队数据访问层（P3）：队伍、成员与邀请。只 flush，不 commit。"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.task import TaskClaim
from app.models.team import Team, TeamInvitation, TeamMember
from app.models.user import User
from app.repositories.base import paginate


class TeamRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ 队伍

    async def create_team(self, data: dict) -> Team:
        team = Team(**data)
        self.db.add(team)
        await self.db.flush()
        return team

    async def get_team(self, team_id: int) -> Optional[Team]:
        return await self.db.get(Team, team_id)

    async def get_team_for_update(self, team_id: int) -> Optional[Team]:
        result = await self.db.execute(
            select(Team).where(Team.id == team_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def update_team(self, team: Team, data: dict) -> None:
        for key, value in data.items():
            setattr(team, key, value)
        self.db.add(team)
        await self.db.flush()

    async def list_teams_for_user(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> List[Team]:
        stmt = (
            select(Team)
            .join(
                TeamMember,
                (TeamMember.team_id == Team.id)
                & (TeamMember.user_id == user_id)
                & (TeamMember.status == "active"),
            )
            .where(Team.status != "archived")
            .order_by(Team.id.desc())
        )
        result = await self.db.execute(paginate(stmt, skip, limit))
        return list(result.scalars().all())

    async def count_teams_for_user(self, user_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Team)
            .join(
                TeamMember,
                (TeamMember.team_id == Team.id)
                & (TeamMember.user_id == user_id)
                & (TeamMember.status == "active"),
            )
            .where(Team.status != "archived")
        )
        return int(result.scalar_one())

    async def team_has_open_claim(self, team_id: int) -> bool:
        result = await self.db.execute(
            select(func.count())
            .select_from(TaskClaim)
            .where(
                TaskClaim.team_id == team_id,
                TaskClaim.status.in_(("active", "submitted")),
            )
        )
        return int(result.scalar_one()) > 0

    # ------------------------------------------------------------------ 成员

    async def add_member(
        self, team_id: int, user_id: int, role: str
    ) -> TeamMember:
        member = TeamMember(team_id=team_id, user_id=user_id, role=role)
        self.db.add(member)
        await self.db.flush()
        return member

    async def get_active_member(
        self, team_id: int, user_id: int
    ) -> Optional[TeamMember]:
        result = await self.db.execute(
            select(TeamMember).where(
                TeamMember.team_id == team_id,
                TeamMember.user_id == user_id,
                TeamMember.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def get_member_any(
        self, team_id: int, user_id: int
    ) -> Optional[TeamMember]:
        result = await self.db.execute(
            select(TeamMember).where(
                TeamMember.team_id == team_id,
                TeamMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def reactivate_member(self, member: TeamMember, role: str) -> None:
        member.status = "active"
        member.role = role
        member.left_at = None
        member.joined_at = now_utc()
        self.db.add(member)
        await self.db.flush()

    async def list_active_members(
        self, team_id: int
    ) -> List[tuple[TeamMember, User]]:
        result = await self.db.execute(
            select(TeamMember, User)
            .join(User, User.id == TeamMember.user_id)
            .where(TeamMember.team_id == team_id, TeamMember.status == "active")
            .order_by(TeamMember.id)
        )
        return list(result.tuples().all())

    async def count_active_members(self, team_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(TeamMember)
            .where(TeamMember.team_id == team_id, TeamMember.status == "active")
        )
        return int(result.scalar_one())

    async def leave_member(
        self, team_id: int, user_id: int, left_at
    ) -> None:
        member = await self.get_active_member(team_id, user_id)
        if member is None:
            return
        member.status = "left"
        member.left_at = left_at
        self.db.add(member)
        await self.db.flush()

    # ------------------------------------------------------------------ 邀请

    async def create_invitation(self, data: dict) -> TeamInvitation:
        invitation = TeamInvitation(**data)
        self.db.add(invitation)
        await self.db.flush()
        return invitation

    async def get_invitation(self, invitation_id: int) -> Optional[TeamInvitation]:
        return await self.db.get(TeamInvitation, invitation_id)

    async def get_invitation_for_update(
        self, invitation_id: int
    ) -> Optional[TeamInvitation]:
        result = await self.db.execute(
            select(TeamInvitation)
            .where(TeamInvitation.id == invitation_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_pending_invitation(
        self, team_id: int, invitee_user_id: int
    ) -> Optional[TeamInvitation]:
        result = await self.db.execute(
            select(TeamInvitation).where(
                TeamInvitation.team_id == team_id,
                TeamInvitation.invitee_user_id == invitee_user_id,
                TeamInvitation.status == "pending",
            )
        )
        return result.scalar_one_or_none()

    async def list_pending_invitations(
        self, invitee_user_id: int, *, skip: int = 0, limit: int = 20
    ) -> List[TeamInvitation]:
        result = await self.db.execute(
            paginate(
                select(TeamInvitation)
                .where(
                    TeamInvitation.invitee_user_id == invitee_user_id,
                    TeamInvitation.status == "pending",
                )
                .order_by(TeamInvitation.id.desc()),
                skip,
                limit,
            )
        )
        return list(result.scalars().all())

    async def count_pending_invitations(self, invitee_user_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(TeamInvitation)
            .where(
                TeamInvitation.invitee_user_id == invitee_user_id,
                TeamInvitation.status == "pending",
            )
        )
        return int(result.scalar_one())

    async def update_invitation(
        self, invitation: TeamInvitation, data: dict
    ) -> None:
        for key, value in data.items():
            setattr(invitation, key, value)
        self.db.add(invitation)
        await self.db.flush()
