"""任务服务：CRUD / 认领（限额）/ 审核（积分联动）。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.timezone import now_utc
from app.models.task import Task, TaskClaim
from app.repositories.tools_repo import TaskRepository
from app.schemas.tools import TaskInput
from app.services.points_service import PointsService


class TaskService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TaskRepository(db)

    # ------------------------------------------------------------------ CRUD

    async def list_tasks(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Task], int]:
        return await self.repo.list_tasks(
            status=status, category=category, skip=skip, limit=limit
        )

    async def get_task(self, task_id: int) -> Task:
        task = await self.repo.get_by_id(task_id)
        if task is None:
            raise NotFoundException(
                message="任务不存在", resource_type="task", resource_id=str(task_id)
            )
        return task

    async def create_task(self, created_by: int, data: TaskInput) -> Task:
        payload = data.model_dump()
        payload["created_by"] = created_by
        task = await self.repo.create(payload)
        await self.db.commit()
        return task

    async def update_task(self, task_id: int, data: TaskInput) -> Task:
        task = await self.get_task(task_id)
        await self.repo.update(task, data.model_dump(exclude_unset=True))
        await self.db.commit()
        return task

    async def publish_task(self, task_id: int) -> Task:
        task = await self.get_task(task_id)
        await self.repo.update(task, {"status": "published", "published_at": now_utc()})
        await self.db.commit()
        return task

    async def close_task(self, task_id: int) -> Task:
        task = await self.get_task(task_id)
        await self.repo.update(task, {"status": "closed", "closed_at": now_utc()})
        await self.db.commit()
        return task

    async def delete_task(self, task_id: int) -> None:
        if not await self.repo.delete(task_id):
            raise NotFoundException(
                message="任务不存在", resource_type="task", resource_id=str(task_id)
            )
        await self.db.commit()

    # ------------------------------------------------------------------ 认领

    async def claim_task(
        self, user_id: int, task_id: int, note: Optional[str] = None
    ) -> TaskClaim:
        task = await self.get_task(task_id)
        if task.status != "published":
            raise ConflictException(
                message="任务未开放", error_code=ErrorCode.Community.STATUS_CONFLICT
            )
        existing = await self.repo.get_claim(task_id, user_id)
        if existing is not None:
            raise ConflictException(
                message="已认领该任务", error_code=ErrorCode.Event.ALREADY_REGISTERED
            )
        active = await self.repo.count_active_claims(task_id)
        if active >= task.max_claimants:
            raise ConflictException(
                message="任务认领名额已满", error_code=ErrorCode.Event.FULL
            )
        claim = await self.repo.create_claim(
            {"task_id": task_id, "user_id": user_id, "claim_note": note}
        )
        await self.db.commit()
        return claim

    async def cancel_claim(self, user_id: int, claim_id: int) -> None:
        claim = await self.repo.get_claim_by_id(claim_id)
        if claim is None or claim.user_id != user_id:
            raise NotFoundException(
                message="认领记录不存在",
                resource_type="task_claim",
                resource_id=str(claim_id),
            )
        if claim.status != "claimed":
            raise ConflictException(
                message="该认领不可取消", error_code=ErrorCode.Community.STATUS_CONFLICT
            )
        await self.db.delete(claim)
        await self.db.commit()

    async def user_claims(self, user_id: int) -> list[TaskClaim]:
        return await self.repo.list_claims_for_user(user_id)

    async def task_claims(self, task_id: int) -> list[TaskClaim]:
        await self.get_task(task_id)
        return await self.repo.list_claims_for_task(task_id)

    async def pending_claims(self) -> list[TaskClaim]:
        return await self.repo.list_pending_claims()

    async def submit_claim(self, user_id: int, claim_id: int) -> TaskClaim:
        """用户提交完成（认领 → submitted）。"""
        claim = await self.repo.get_claim_by_id(claim_id)
        if claim is None or claim.user_id != user_id:
            raise NotFoundException(
                message="认领记录不存在",
                resource_type="task_claim",
                resource_id=str(claim_id),
            )
        if claim.status != "claimed":
            raise ConflictException(
                message="该认领不可提交", error_code=ErrorCode.Community.STATUS_CONFLICT
            )
        claim.status = "submitted"
        claim.completed_at = now_utc()
        await self.db.commit()
        return claim

    async def review_claim(
        self, admin_id: int, claim_id: int, approved: bool, note: Optional[str]
    ) -> TaskClaim:
        claim = await self.repo.get_claim_by_id(claim_id)
        if claim is None:
            raise NotFoundException(
                message="认领记录不存在",
                resource_type="task_claim",
                resource_id=str(claim_id),
            )
        if claim.status not in ("claimed", "submitted"):
            raise ConflictException(
                message="该认领已处理", error_code=ErrorCode.Validation.ALREADY_REVIEWED
            )
        if approved:
            claim.status = "approved"
            claim.reviewed_by = admin_id
            claim.review_note = note
            # 积分联动
            task = await self.get_task(claim.task_id)
            points = PointsService(self.db)
            await points.add_points(
                claim.user_id, task.points, "task", task.id, f"完成任务：{task.title}"
            )
        else:
            claim.status = "rejected"
            claim.reviewed_by = admin_id
            claim.review_note = note
        await self.db.commit()
        return claim
