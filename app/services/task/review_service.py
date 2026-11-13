"""任务审核、成果验收与强制结项（P3）。

资金路径与状态变更在同一事务内完成；reward/refund 共享 settlement 业务键。
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.timezone import now_utc
from app.models.task import (
    TASK_STATUS_CLOSED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_EXPIRED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_PENDING_REVIEW,
    TASK_STATUS_PUBLISHED,
    TASK_STATUS_REJECTED,
    TASK_STATUS_SUBMITTED,
    Task,
)
from app.models.user import User
from app.repositories.task_repo import TaskRepository
from app.schemas.task import SubmissionReviewCreate, TaskReviewCreate
from app.services.task.access import (
    claim_to_dict,
    get_publisher_name,
    require_future,
    task_to_dict,
)
from app.services.task.settlement import refund_reward, reserve_reward, settle_reward
from app.services.wallet.idempotency_service import (
    IdempotencyService,
    require_idempotency_key,
)

_OP_TASK_REVIEW = "task_review"
_OP_SUBMISSION_REVIEW = "task_submission_review"
_OP_FORCE_CLOSE = "task_force_close"


def _task_not_found(task_id: int) -> NotFoundException:
    return NotFoundException(
        message="任务不存在", resource_type="task", resource_id=str(task_id)
    )


class TaskReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TaskRepository(db)
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

    async def _add_action(
        self,
        *,
        task: Task,
        actor_id: int,
        action: str,
        from_status: Optional[str],
        claim_id: Optional[int] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        await self.repo.add_action(
            {
                "task_id": task.id,
                "claim_id": claim_id,
                "actor_id": actor_id,
                "action": action,
                "from_status": from_status,
                "to_status": task.status,
                "reason": reason,
                "request_id": request_id,
            }
        )

    # ------------------------------------------------------------------ 上架审核

    async def review_task(
        self,
        *,
        actor: User,
        task_id: int,
        data: TaskReviewCreate,
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"task_id": task_id, **data.model_dump()}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_TASK_REVIEW, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        task = await self.repo.get_for_update(task_id)
        if task is None:
            raise _task_not_found(task_id)
        if task.publisher_id == actor.id:
            raise AuthorizationException(
                message="不能审核自己发布的任务",
                error_code=ErrorCode.Authorization.SELF_REVIEW_FORBIDDEN,
            )
        if task.status != TASK_STATUS_PENDING_REVIEW:
            raise ConflictException(
                message="任务不在待审核状态",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        previous = task.status
        if data.decision == "approve":
            await reserve_reward(
                self.db,
                task=task,
                actor_id=actor.id,
                request_id=request_id,
            )
            await self.repo.update(
                task,
                {
                    "status": TASK_STATUS_PUBLISHED,
                    "reviewed_at": now_utc(),
                    "published_at": now_utc(),
                    "version": task.version + 1,
                },
            )
            await self._add_action(
                task=task,
                actor_id=actor.id,
                action="approve",
                from_status=previous,
                reason=data.note,
                request_id=request_id,
            )
        else:
            await self.repo.update(
                task,
                {
                    "status": TASK_STATUS_REJECTED,
                    "reviewed_at": now_utc(),
                    "version": task.version + 1,
                },
            )
            await self._add_action(
                task=task,
                actor_id=actor.id,
                action="reject",
                from_status=previous,
                reason=data.note,
                request_id=request_id,
            )
        response = task_to_dict(task, await get_publisher_name(self.db, task.publisher_id))
        return await self._save(
            actor_id=actor.id,
            operation=_OP_TASK_REVIEW,
            key=key,
            payload=payload,
            response=response,
        )

    # ------------------------------------------------------------------ 成果验收

    async def review_submission(
        self,
        *,
        actor: User,
        submission_id: int,
        data: SubmissionReviewCreate,
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"submission_id": submission_id, **data.model_dump(mode="json")}
        key, replay = await self._begin(
            actor_id=actor.id,
            operation=_OP_SUBMISSION_REVIEW,
            key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay

        submission = await self.repo.get_submission(submission_id)
        if submission is None:
            raise NotFoundException(
                message="成果记录不存在",
                resource_type="task_submission",
                resource_id=str(submission_id),
            )
        claim = await self.repo.get_claim(submission.claim_id)
        if claim is None:
            raise NotFoundException(
                message="执行记录不存在",
                resource_type="task_claim",
                resource_id=submission.claim_id,
            )
        task = await self.repo.get_for_update(claim.task_id)
        if task is None:
            raise _task_not_found(claim.task_id)
        claim = await self.repo.get_claim_for_update(claim.id)
        submission = await self.repo.get_submission_for_update(submission_id)
        if claim is None or submission is None:
            raise NotFoundException(message="成果或执行记录不存在")
        if submission.review_status != "pending":
            raise ConflictException(
                message="该成果已处理",
                error_code=ErrorCode.Conflict.TASK_ALREADY_SETTLED,
            )
        if claim.status != "submitted" or task.status != TASK_STATUS_SUBMITTED:
            raise ConflictException(
                message="任务不在待验收状态",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        if await self._is_self_review(task, claim, actor.id):
            raise AuthorizationException(
                message="不能验收自己参与的任务成果",
                error_code=ErrorCode.Authorization.SELF_REVIEW_FORBIDDEN,
            )

        previous = task.status
        if data.decision == "approve":
            await settle_reward(
                self.db,
                task=task,
                claim=claim,
                actor_id=actor.id,
                request_id=request_id,
            )
            await self.repo.update_claim(
                claim,
                {
                    "status": "completed",
                    "completed_at": now_utc(),
                    "version": claim.version + 1,
                },
            )
            await self.repo.update(
                task,
                {
                    "status": TASK_STATUS_COMPLETED,
                    "closed_at": now_utc(),
                    "version": task.version + 1,
                },
            )
            submission.review_status = "approved"
            submission.reviewer_id = actor.id
            submission.review_note = data.note
            submission.reviewed_at = now_utc()
            self.db.add(submission)
            await self.db.flush()
            await self._add_action(
                task=task,
                claim_id=claim.id,
                actor_id=actor.id,
                action="accept",
                from_status=previous,
                reason=data.note,
                request_id=request_id,
            )
        else:
            require_future(data.rework_deadline, message="返工截止时间必须晚于当前时间")
            submission.review_status = "rejected"
            submission.reviewer_id = actor.id
            submission.review_note = data.note
            submission.reviewed_at = now_utc()
            self.db.add(submission)
            await self.db.flush()
            await self.repo.update_claim(
                claim,
                {
                    "status": "active",
                    "submitted_at": None,
                    "version": claim.version + 1,
                },
            )
            await self.repo.update(
                task,
                {
                    "status": TASK_STATUS_IN_PROGRESS,
                    "deadline": data.rework_deadline,
                    "version": task.version + 1,
                },
            )
            await self._add_action(
                task=task,
                claim_id=claim.id,
                actor_id=actor.id,
                action="reject_submission",
                from_status=previous,
                reason=data.note,
                request_id=request_id,
            )

        members = await self.repo.list_claim_members(claim.id)
        response = claim_to_dict(claim, members, submission)
        return await self._save(
            actor_id=actor.id,
            operation=_OP_SUBMISSION_REVIEW,
            key=key,
            payload=payload,
            response=response,
        )

    async def _is_self_review(self, task: Task, claim, reviewer_id: int) -> bool:
        if task.publisher_id == reviewer_id or claim.leader_user_id == reviewer_id:
            return True
        members = await self.repo.list_claim_members(claim.id)
        return any(member.user_id == reviewer_id for member, _ in members)

    # ------------------------------------------------------------------ 强制结项

    async def force_close(
        self,
        *,
        actor: User,
        task_id: int,
        reason: str,
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"task_id": task_id, "reason": reason}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_FORCE_CLOSE, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        task = await self.repo.get_for_update(task_id)
        if task is None:
            raise _task_not_found(task_id)
        if task.status not in (
            TASK_STATUS_PUBLISHED,
            TASK_STATUS_IN_PROGRESS,
            TASK_STATUS_SUBMITTED,
        ):
            raise ConflictException(
                message="当前状态不可强制结项",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        previous = task.status
        claim = await self.repo.get_open_claim(task.id)
        await refund_reward(
            self.db,
            task=task,
            actor_id=actor.id,
            reason=reason,
            request_id=request_id,
        )
        if claim is not None:
            await self.repo.update_claim(
                claim,
                {"status": "cancelled", "version": claim.version + 1},
            )
        await self.repo.update(
            task,
            {
                "status": TASK_STATUS_CLOSED,
                "closed_at": now_utc(),
                "version": task.version + 1,
            },
        )
        await self._add_action(
            task=task,
            claim_id=claim.id if claim is not None else None,
            actor_id=actor.id,
            action="force_close",
            from_status=previous,
            reason=reason,
            request_id=request_id,
        )
        response = task_to_dict(task, await get_publisher_name(self.db, task.publisher_id))
        return await self._save(
            actor_id=actor.id,
            operation=_OP_FORCE_CLOSE,
            key=key,
            payload=payload,
            response=response,
        )

    # ------------------------------------------------------------------ 到期退款

    async def expire_if_due(self, *, task_id: int) -> Optional[dict]:
        """到期任务退款；submitted 不自动退款，等待验收。"""
        task = await self.repo.get_for_update(task_id)
        if task is None or task.status not in (
            TASK_STATUS_PUBLISHED,
            TASK_STATUS_IN_PROGRESS,
        ):
            return None
        if task.deadline is None or task.deadline > now_utc():
            return None
        previous = task.status
        claim = await self.repo.get_open_claim(task.id)
        await refund_reward(
            self.db,
            task=task,
            actor_id=task.publisher_id,
            reason="任务到期自动退款",
        )
        if claim is not None:
            await self.repo.update_claim(
                claim,
                {"status": "cancelled", "version": claim.version + 1},
            )
        await self.repo.update(
            task,
            {
                "status": TASK_STATUS_EXPIRED,
                "closed_at": now_utc(),
                "version": task.version + 1,
            },
        )
        await self._add_action(
            task=task,
            claim_id=claim.id if claim is not None else None,
            actor_id=task.publisher_id,
            action="expire",
            from_status=previous,
            reason="任务到期自动退款",
        )
        return task_to_dict(task)

    # ------------------------------------------------------------------ 管理端列表

    async def list_admin_tasks(
        self,
        *,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        peak_id: Optional[int] = None,
        publisher_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[dict], int]:
        conditions = []
        if status:
            conditions.append(Task.status == status)
        if peak_id is not None:
            conditions.append(Task.peak_id == peak_id)
        if publisher_id is not None:
            conditions.append(Task.publisher_id == publisher_id)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(Task.title.ilike(pattern), Task.description.ilike(pattern))
            )
        rows = await self.repo.list_tasks(
            conditions=conditions, skip=skip, limit=limit
        )
        total = await self.repo.count_tasks(conditions=conditions)
        items = [
            task_to_dict(row, await get_publisher_name(self.db, row.publisher_id))
            for row in rows
        ]
        return items, total
