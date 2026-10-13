"""任务仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskClaim
from app.repositories.base import paginate


class TaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_tasks(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Task], int]:
        conditions = []
        if status:
            conditions.append(Task.status == status)
        if category:
            conditions.append(Task.category == category)
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Task).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(Task).where(*conditions).order_by(Task.created_at.desc()),
            skip,
            limit,
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, task_id: int) -> Optional[Task]:
        return await self.db.get(Task, task_id)

    async def create(self, data: dict) -> Task:
        obj = Task(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, task: Task, data: dict) -> None:
        for key, value in data.items():
            setattr(task, key, value)

    async def delete(self, task_id: int) -> bool:
        obj = await self.get_by_id(task_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def count_active_claims(self, task_id: int) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(TaskClaim)
                    .where(
                        TaskClaim.task_id == task_id,
                        TaskClaim.status.in_(["claimed", "submitted"]),
                    )
                )
            ).scalar_one()
        )

    async def count_active_claims_by_ids(self, task_ids: list[int]) -> dict[int, int]:
        """一次 GROUP BY 统计多个任务的活跃认领数（口径与 count_active_claims 一致），
        供任务列表批量填充 claimant_count，避免逐任务查询的 N+1（TOOLS-GOV Slice E）。"""
        if not task_ids:
            return {}
        rows = (
            await self.db.execute(
                select(
                    TaskClaim.task_id,
                    func.count().label("cnt"),
                )
                .where(
                    TaskClaim.task_id.in_(task_ids),
                    TaskClaim.status.in_(["claimed", "submitted"]),
                )
                .group_by(TaskClaim.task_id)
            )
        ).all()
        return {task_id: int(cnt) for task_id, cnt in rows}

    async def get_claim(self, task_id: int, user_id: int) -> Optional[TaskClaim]:
        stmt = select(TaskClaim).where(
            TaskClaim.task_id == task_id, TaskClaim.user_id == user_id
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def get_claim_by_id(self, claim_id: int) -> Optional[TaskClaim]:
        return await self.db.get(TaskClaim, claim_id)

    async def create_claim(self, data: dict) -> TaskClaim:
        obj = TaskClaim(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def list_claims_for_task(self, task_id: int) -> list[TaskClaim]:
        stmt = (
            select(TaskClaim)
            .where(TaskClaim.task_id == task_id)
            .order_by(TaskClaim.created_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_claims_for_user(self, user_id: int) -> list[TaskClaim]:
        stmt = (
            select(TaskClaim)
            .where(TaskClaim.user_id == user_id)
            .order_by(TaskClaim.created_at.desc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_pending_claims(self) -> list[TaskClaim]:
        stmt = (
            select(TaskClaim)
            .where(TaskClaim.status == "submitted")
            .order_by(TaskClaim.created_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())