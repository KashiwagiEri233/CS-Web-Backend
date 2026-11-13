"""团队模型（P3）：teams / team_members / team_invitations。

团队是任务执行的业务组织，不是全局 RBAC 角色。执行中名单锁定在
task_claim_members 快照，本表后续变化不影响已接取任务。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime as _DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)

TEAM_STATUS_FORMING = "forming"
TEAM_STATUS_ACTIVE = "active"
TEAM_STATUS_ARCHIVED = "archived"

TEAM_MEMBER_ROLE_CAPTAIN = "captain"
TEAM_MEMBER_ROLE_MEMBER = "member"

TEAM_MEMBER_STATUS_ACTIVE = "active"
TEAM_MEMBER_STATUS_LEFT = "left"

INVITATION_STATUS_PENDING = "pending"
INVITATION_STATUS_ACCEPTED = "accepted"
INVITATION_STATUS_REJECTED = "rejected"
INVITATION_STATUS_EXPIRED = "expired"
INVITATION_STATUS_CANCELLED = "cancelled"


class Team(Base):
    """临时任务队伍：队长必须是在册成员。"""

    __tablename__ = "teams"
    __table_args__ = (
        CheckConstraint(
            "status IN ('forming', 'active', 'archived')", name="ck_teams_status"
        ),
        Index("ix_teams_captain", "captain_user_id"),
        Index("ix_teams_status_created", "status", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    captain_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TEAM_STATUS_FORMING
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<Team(id={self.id}, name='{self.name}', status='{self.status}')>"


class TeamMember(Base):
    """队伍成员：有效成员唯一，有效队长每队唯一。"""

    __tablename__ = "team_members"
    __table_args__ = (
        CheckConstraint("role IN ('captain', 'member')", name="ck_team_members_role"),
        CheckConstraint(
            "status IN ('active', 'left')", name="ck_team_members_status"
        ),
        Index(
            "uq_team_members_active_user",
            "team_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_team_members_active_captain",
            "team_id",
            unique=True,
            postgresql_where=text("role = 'captain' AND status = 'active'"),
        ),
        Index("ix_team_members_user", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TEAM_MEMBER_STATUS_ACTIVE
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TeamInvitation(Base):
    """入队邀请：只能本人确认，过期不影响账号。"""

    __tablename__ = "team_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'expired', 'cancelled')",
            name="ck_team_invitations_status",
        ),
        Index(
            "uq_team_invitations_pending",
            "team_id",
            "invitee_user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_team_invitations_invitee", "invitee_user_id", "status"),
        Index("ix_team_invitations_expires", "expires_at", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id"), nullable=False
    )
    invitee_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    inviter_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=INVITATION_STATUS_PENDING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
