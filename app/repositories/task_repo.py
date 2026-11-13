"""任务域数据访问层（P3）：任务、执行实例、成果、历史。

只 flush，不 commit；锁顺序由 service 统一控制。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.task import (
    Task,
    TaskAction,
    TaskClaim,
    TaskClaimMember,
    TaskSubmission,
)
from app.models.user import User
from app.models.wallet import LedgerTransaction
from app.repositories.base import paginate

_OPEN_CLAIM_STATUSES = ("active", "submitted", "completed")


class TaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ 任务

    async def create(self, data: dict) -> Task:
        task = Task(**data)
        self.db.add(task)
        await self.db.flush()
        return task

    async def get(self, task_id: int) -> Optional[Task]:
        return await self.db.get(Task, task_id)

    async def get_for_update(self, task_id: int) -> Optional[Task]:
        result = await self.db.execute(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def update(self, task: Task, data: dict) -> None:
        for key, value in data.items():
            setattr(task, key, value)
        self.db.add(task)
        await self.db.flush()

    async def list_tasks(
        self,
        *,
        conditions: Sequence = (),
        skip: int = 0,
        limit: int = 20,
    ) -> List[Task]:
        stmt = (
            select(Task)
            .where(*conditions)
            .order_by(Task.created_at.desc(), Task.id.desc())
        )
        result = await self.db.execute(paginate(stmt, skip, limit))
        return list(result.scalars().all())

    async def count_tasks(self, *, conditions: Sequence = ()) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(Task).where(*conditions)
        )
        return int(result.scalar_one())

    async def list_due_task_ids(self, *, limit: int) -> List[int]:
        """到期待处理任务 ID；只取 published / in_progress，submitted 等待验收。"""
        result = await self.db.execute(
            select(Task.id)
            .where(
                Task.status.in_(("published", "in_progress")),
                Task.deadline.is_not(None),
                Task.deadline <= now_utc(),
            )
            .order_by(Task.deadline, Task.id)
            .limit(limit)
        )
        return [int(task_id) for task_id in result.scalars().all()]

    # -------------------------------------------------------------- 执行实例

    async def get_open_claim(self, task_id: int) -> Optional[TaskClaim]:
        result = await self.db.execute(
            select(TaskClaim).where(
                TaskClaim.task_id == task_id,
                TaskClaim.status.in_(_OPEN_CLAIM_STATUSES),
            )
        )
        return result.scalar_one_or_none()

    async def get_claim(self, claim_id: int) -> Optional[TaskClaim]:
        return await self.db.get(TaskClaim, claim_id)

    async def get_claim_for_update(self, claim_id: int) -> Optional[TaskClaim]:
        result = await self.db.execute(
            select(TaskClaim).where(TaskClaim.id == claim_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_claim(self, data: dict) -> TaskClaim:
        claim = TaskClaim(**data)
        self.db.add(claim)
        await self.db.flush()
        return claim

    async def update_claim(self, claim: TaskClaim, data: dict) -> None:
        for key, value in data.items():
            setattr(claim, key, value)
        self.db.add(claim)
        await self.db.flush()

    async def add_claim_member(
        self, claim_id: int, user_id: int, is_leader: bool
    ) -> TaskClaimMember:
        member = TaskClaimMember(
            claim_id=claim_id, user_id=user_id, is_leader=is_leader
        )
        self.db.add(member)
        await self.db.flush()
        return member

    async def list_claim_members(
        self, claim_id: int
    ) -> List[tuple[TaskClaimMember, User]]:
        result = await self.db.execute(
            select(TaskClaimMember, User)
            .join(User, User.id == TaskClaimMember.user_id)
            .where(TaskClaimMember.claim_id == claim_id)
            .order_by(TaskClaimMember.id)
        )
        return list(result.tuples().all())

    async def list_claims_for_task(self, task_id: int) -> List[TaskClaim]:
        result = await self.db.execute(
            select(TaskClaim)
            .where(TaskClaim.task_id == task_id)
            .order_by(TaskClaim.id.desc())
        )
        return list(result.scalars().all())

    async def list_claims_for_user(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> List[TaskClaim]:
        stmt = (
            select(TaskClaim)
            .join(TaskClaimMember, TaskClaimMember.claim_id == TaskClaim.id)
            .where(TaskClaimMember.user_id == user_id)
            .order_by(TaskClaim.started_at.desc(), TaskClaim.id.desc())
            .distinct()
        )
        result = await self.db.execute(paginate(stmt, skip, limit))
        return list(result.scalars().all())

    async def count_claims_for_user(self, user_id: int) -> int:
        result = await self.db.execute(
            select(func.count(func.distinct(TaskClaim.id)))
            .select_from(TaskClaim)
            .join(TaskClaimMember, TaskClaimMember.claim_id == TaskClaim.id)
            .where(TaskClaimMember.user_id == user_id)
        )
        return int(result.scalar_one())

    async def user_has_active_claim(self, user_id: int) -> bool:
        result = await self.db.execute(
            select(func.count())
            .select_from(TaskClaim)
            .join(TaskClaimMember, TaskClaimMember.claim_id == TaskClaim.id)
            .where(
                TaskClaimMember.user_id == user_id,
                TaskClaim.status.in_(("active", "submitted")),
            )
        )
        return int(result.scalar_one()) > 0

    # ------------------------------------------------------------------ 成果

    async def next_revision(self, claim_id: int) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.max(TaskSubmission.revision), 0)).where(
                TaskSubmission.claim_id == claim_id
            )
        )
        return int(result.scalar_one()) + 1

    async def create_submission(self, data: dict) -> TaskSubmission:
        submission = TaskSubmission(**data)
        self.db.add(submission)
        await self.db.flush()
        return submission

    async def get_submission(self, submission_id: int) -> Optional[TaskSubmission]:
        return await self.db.get(TaskSubmission, submission_id)

    async def get_submission_for_update(
        self, submission_id: int
    ) -> Optional[TaskSubmission]:
        result = await self.db.execute(
            select(TaskSubmission)
            .where(TaskSubmission.id == submission_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def latest_submission(self, claim_id: int) -> Optional[TaskSubmission]:
        result = await self.db.execute(
            select(TaskSubmission)
            .where(TaskSubmission.claim_id == claim_id)
            .order_by(TaskSubmission.revision.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def pending_submission(self, claim_id: int) -> Optional[TaskSubmission]:
        result = await self.db.execute(
            select(TaskSubmission).where(
                TaskSubmission.claim_id == claim_id,
                TaskSubmission.review_status == "pending",
            )
        )
        return result.scalar_one_or_none()

    async def list_submissions(self, claim_id: int) -> List[TaskSubmission]:
        result = await self.db.execute(
            select(TaskSubmission)
            .where(TaskSubmission.claim_id == claim_id)
            .order_by(TaskSubmission.revision)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------ 历史

    async def add_action(self, data: dict) -> TaskAction:
        action = TaskAction(**data)
        self.db.add(action)
        await self.db.flush()
        return action

    async def list_actions(
        self, task_id: int, *, skip: int = 0, limit: int = 50
    ) -> List[TaskAction]:
        result = await self.db.execute(
            paginate(
                select(TaskAction)
                .where(TaskAction.task_id == task_id)
                .order_by(TaskAction.id.desc()),
                skip,
                limit,
            )
        )
        return list(result.scalars().all())

    async def count_actions(self, task_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(TaskAction)
            .where(TaskAction.task_id == task_id)
        )
        return int(result.scalar_one())

    # ------------------------------------------------------------------ 结算

    async def get_settlement_transaction(self, task_id: int) -> Optional[LedgerTransaction]:
        result = await self.db.execute(
            select(LedgerTransaction).where(
                LedgerTransaction.business_key == f"task:{task_id}:settlement"
            )
        )
        return result.scalar_one_or_none()
