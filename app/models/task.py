"""任务与执行模型（P3）：tasks / task_claims / 成果 / 动作。

设计要点：
- 一个任务只有一个当前执行实例（claim），团队模式由 claim 成员快照表达。
- 奖励全额托管在任务 escrow 账户，验收时全额支付给锁定的队长（单人即本人）。
- 状态值使用英文机器值，旧端中文展示由前端/契约映射。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime as _DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)

# ---- 任务状态 ----
TASK_STATUS_DRAFT = "draft"
TASK_STATUS_PENDING_REVIEW = "pending_review"
TASK_STATUS_REJECTED = "rejected"
TASK_STATUS_PUBLISHED = "published"
TASK_STATUS_IN_PROGRESS = "in_progress"
TASK_STATUS_SUBMITTED = "submitted"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_CLOSED = "closed"
TASK_STATUS_EXPIRED = "expired"

TASK_STATUSES = (
    TASK_STATUS_DRAFT,
    TASK_STATUS_PENDING_REVIEW,
    TASK_STATUS_REJECTED,
    TASK_STATUS_PUBLISHED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_SUBMITTED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_CLOSED,
    TASK_STATUS_EXPIRED,
)
# 非终态（资金仍可托管或应退款）
TASK_ACTIVE_STATUSES = (
    TASK_STATUS_PUBLISHED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_SUBMITTED,
)
TASK_FINISHED_STATUSES = (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_CLOSED,
    TASK_STATUS_EXPIRED,
)

# ---- 执行模式 ----
EXECUTION_MODE_SINGLE = "single"
EXECUTION_MODE_TEAM = "team"
EXECUTION_MODES = (EXECUTION_MODE_SINGLE, EXECUTION_MODE_TEAM)

# ---- 可见范围 ----
VISIBILITY_PUBLIC = "public"
VISIBILITY_MEMBERS = "members"
VISIBILITY_PEAK = "peak"
VISIBILITIES = (VISIBILITY_PUBLIC, VISIBILITY_MEMBERS, VISIBILITY_PEAK)

# ---- 执行实例状态 ----
CLAIM_STATUS_ACTIVE = "active"
CLAIM_STATUS_SUBMITTED = "submitted"
CLAIM_STATUS_COMPLETED = "completed"
CLAIM_STATUS_CANCELLED = "cancelled"
CLAIM_STATUSES = (
    CLAIM_STATUS_ACTIVE,
    CLAIM_STATUS_SUBMITTED,
    CLAIM_STATUS_COMPLETED,
    CLAIM_STATUS_CANCELLED,
)

# ---- 成果审核状态 ----
SUBMISSION_REVIEW_PENDING = "pending"
SUBMISSION_REVIEW_APPROVED = "approved"
SUBMISSION_REVIEW_REJECTED = "rejected"


class Task(Base):
    """协会任务：draft → pending_review → published → in_progress → submitted → 终态。"""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("reward_total >= 1", name="ck_tasks_reward_positive"),
        CheckConstraint(
            "execution_mode IN ('single', 'team')", name="ck_tasks_execution_mode"
        ),
        CheckConstraint(
            "(execution_mode = 'single' AND max_members = 1) "
            "OR (execution_mode = 'team' AND max_members >= 2)",
            name="ck_tasks_member_count",
        ),
        CheckConstraint(
            "visibility IN ('public', 'members', 'peak')",
            name="ck_tasks_visibility",
        ),
        CheckConstraint(
            "visibility <> 'peak' OR peak_id IS NOT NULL",
            name="ck_tasks_peak_visibility",
        ),
        Index("ix_tasks_status_deadline", "status", "deadline", "id"),
        Index("ix_tasks_publisher_created", "publisher_id", "created_at", "id"),
        Index("ix_tasks_peak_status", "peak_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    content_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="general", index=True
    )
    tags: Mapped[Optional[list]] = mapped_column(JSONDict, nullable=True, default=list)
    execution_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default=EXECUTION_MODE_SINGLE
    )
    reward_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=10)
    max_members: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TASK_STATUS_DRAFT, index=True
    )
    publisher_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VISIBILITY_MEMBERS
    )
    peak_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("peaks.id", ondelete="SET NULL"), nullable=True
    )
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title='{self.title}', status='{self.status}')>"


class TaskClaim(Base):
    """任务当前执行实例：每任务最多一个非取消实例。"""

    __tablename__ = "task_claims"
    __table_args__ = (
        Index(
            "uq_task_claims_open_task",
            "task_id",
            unique=True,
            postgresql_where=text(
                "status IN ('active', 'submitted', 'completed')"
            ),
        ),
        Index(
            "uq_task_claims_open_team",
            "team_id",
            unique=True,
            postgresql_where=text(
                "team_id IS NOT NULL AND status IN ('active', 'submitted')"
            ),
        ),
        Index("ix_task_claims_leader", "leader_user_id"),
        Index("ix_task_claims_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=False, index=True
    )
    team_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("teams.id"), nullable=True
    )
    leader_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CLAIM_STATUS_ACTIVE, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return (
            f"<TaskClaim(id={self.id}, task_id={self.task_id}, "
            f"leader_user_id={self.leader_user_id})>"
        )


class TaskClaimMember(Base):
    """接取瞬间的成员快照：执行期间不可变更。"""

    __tablename__ = "task_claim_members"
    __table_args__ = (
        UniqueConstraint(
            "claim_id", "user_id", name="uq_task_claim_members_claim_user"
        ),
        Index(
            "uq_task_claim_members_leader",
            "claim_id",
            unique=True,
            postgresql_where=text("is_leader"),
        ),
        Index("ix_task_claim_members_user", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("task_claims.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    is_leader: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class TaskSubmission(Base):
    """版本化成果：保留全部提交历史，每实例最多一条待审。"""

    __tablename__ = "task_submissions"
    __table_args__ = (
        UniqueConstraint(
            "claim_id", "revision", name="uq_task_submissions_claim_revision"
        ),
        Index(
            "uq_task_submissions_pending",
            "claim_id",
            unique=True,
            postgresql_where=text("review_status = 'pending'"),
        ),
        Index("ix_task_submissions_claim_id", "claim_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("task_claims.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attachments: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    submitted_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SUBMISSION_REVIEW_PENDING
    )
    reviewer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TaskAction(Base):
    """任务状态历史：追加写，不替代通用安全审计。"""

    __tablename__ = "task_actions"
    __table_args__ = (
        Index("ix_task_actions_task_id", "task_id", "id"),
        Index("ix_task_actions_claim_id", "claim_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=False
    )
    claim_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("task_claims.id"), nullable=True
    )
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
