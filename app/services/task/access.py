"""任务域共享规则：成员资格、可见范围与序列化。"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    ErrorCode,
    ValidationException,
)
from app.core.timezone import now_utc
from app.models.organization import MemberProfile
from app.models.task import (
    Task,
    TaskClaim,
    TaskSubmission,
    VISIBILITY_MEMBERS,
    VISIBILITY_PEAK,
    VISIBILITY_PUBLIC,
)
from app.models.user import User
from app.repositories.organization_repo import OrganizationRepository


async def load_active_member(
    db: AsyncSession, user_id: int
) -> Optional[MemberProfile]:
    """读取有效成员档案；非成员/停用/离会返回 None。"""
    member = await OrganizationRepository(db).get_member_by_user_id(user_id)
    if member is None or member.membership_status != "active":
        return None
    return member


async def require_active_member(
    db: AsyncSession, user_id: int
) -> MemberProfile:
    """接取/组队要求有效成员资格。"""
    member = await load_active_member(db, user_id)
    if member is None:
        raise AuthorizationException(
            message="仅有效协会成员可执行任务",
            error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
        )
    return member


def require_future(deadline, message: str = "截止时间必须晚于当前时间") -> None:
    """截止时间必须显式给出且晚于当前时间。"""
    if deadline is None:
        raise ValidationException(
            message="必须指定截止时间",
            error_code=ErrorCode.Validation.INVALID_DEADLINE,
        )
    if deadline <= now_utc():
        raise ValidationException(
            message=message, error_code=ErrorCode.Validation.INVALID_DEADLINE
        )


def can_view_task(
    task: Task, user_id: int, member: Optional[MemberProfile]
) -> bool:
    """所有者始终可见；其余按 public/members/peak 范围判断。"""
    if task.publisher_id == user_id:
        return True
    if task.visibility == VISIBILITY_PUBLIC:
        return True
    if member is None:
        return False
    if task.visibility == VISIBILITY_MEMBERS:
        return True
    if task.visibility == VISIBILITY_PEAK:
        return task.peak_id is not None and member.peak_id == task.peak_id
    return False


def visibility_conditions(
    user_id: int, member: Optional[MemberProfile]
) -> Sequence:
    """列表查询的可见范围条件。"""
    clauses = [
        Task.visibility == VISIBILITY_PUBLIC,
        Task.publisher_id == user_id,
    ]
    if member is not None:
        clauses.append(Task.visibility == VISIBILITY_MEMBERS)
        if member.peak_id is not None:
            clauses.append(
                and_(
                    Task.visibility == VISIBILITY_PEAK,
                    Task.peak_id == member.peak_id,
                )
            )
    return [or_(*clauses)]


def submission_to_dict(submission: Optional[TaskSubmission]) -> Optional[dict]:
    if submission is None:
        return None
    return {
        "id": submission.id,
        "claim_id": submission.claim_id,
        "revision": submission.revision,
        "description": submission.description,
        "attachments": list(submission.attachments or []),
        "submitted_by": submission.submitted_by,
        "review_status": submission.review_status,
        "reviewer_id": submission.reviewer_id,
        "review_note": submission.review_note,
        "created_at": submission.created_at,
        "reviewed_at": submission.reviewed_at,
    }


def claim_to_dict(
    claim: TaskClaim,
    members: Sequence[tuple],
    submission: Optional[TaskSubmission] = None,
    task: Optional[Task] = None,
) -> dict:
    return {
        "id": claim.id,
        "task_id": claim.task_id,
        "team_id": claim.team_id,
        "leader_user_id": claim.leader_user_id,
        "status": claim.status,
        "started_at": claim.started_at,
        "submitted_at": claim.submitted_at,
        "completed_at": claim.completed_at,
        "version": claim.version,
        "members": [
            {
                "user_id": member.user_id,
                "display_name": user.display_name or user.username,
                "is_leader": member.is_leader,
            }
            for member, user in members
        ],
        "submission": submission_to_dict(submission),
        "task": task_to_dict(task) if task is not None else None,
    }


def task_to_dict(task: Task, publisher_name: Optional[str] = None) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "content_markdown": task.content_markdown,
        "difficulty": task.difficulty,
        "category": task.category,
        "tags": list(task.tags or []),
        "execution_mode": task.execution_mode,
        "reward_total": int(task.reward_total),
        "max_members": task.max_members,
        "status": task.status,
        "publisher_id": task.publisher_id,
        "publisher_name": publisher_name,
        "visibility": task.visibility,
        "peak_id": task.peak_id,
        "deadline": task.deadline,
        "version": task.version,
        "review_cycle": task.review_cycle,
        "reviewed_at": task.reviewed_at,
        "published_at": task.published_at,
        "closed_at": task.closed_at,
        "archived_at": task.archived_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def team_to_dict(team, members: Sequence[tuple]) -> dict:
    return {
        "id": team.id,
        "name": team.name,
        "captain_user_id": team.captain_user_id,
        "status": team.status,
        "version": team.version,
        "members": [
            {
                "user_id": member.user_id,
                "display_name": user.display_name or user.username,
                "role": member.role,
                "status": member.status,
                "joined_at": member.joined_at,
            }
            for member, user in members
        ],
        "created_at": team.created_at,
        "updated_at": team.updated_at,
    }


async def get_publisher_name(db: AsyncSession, publisher_id: int) -> Optional[str]:
    publisher = await db.get(User, publisher_id)
    if publisher is None:
        return None
    return publisher.display_name or publisher.username
