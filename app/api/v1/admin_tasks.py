"""管理员任务 API（P3）：待审核列表、上架审核、成果验收、强制结项。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_client_meta
from app.database import get_db
from app.dependencies_services import get_audit_service
from app.middleware.rbac import require_admin_2fa, require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.task import (
    ForceCloseCreate,
    SubmissionReviewCreate,
    TaskClaimOut,
    TaskOut,
    TaskReviewCreate,
)
from app.services.audit_service import AuditService
from app.services.task.review_service import TaskReviewService

router = APIRouter(dependencies=[Depends(require_admin_2fa())])


def get_review_service(db: AsyncSession = Depends(get_db)) -> TaskReviewService:
    return TaskReviewService(db)


@router.get("/tasks", response_model=PaginatedResponse[TaskOut])
async def list_admin_tasks(
    pagination: PaginationParams = Depends(),
    status: Optional[str] = None,
    keyword: Optional[str] = Query(None, max_length=50),
    peak_id: Optional[int] = Query(None, gt=0),
    publisher_id: Optional[int] = Query(None, gt=0),
    service: TaskReviewService = Depends(get_review_service),
    current_user: User = Depends(require_permission("task", "read")),
) -> Any:
    items, total = await service.list_admin_tasks(
        status=status,
        keyword=keyword,
        peak_id=peak_id,
        publisher_id=publisher_id,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.post("/tasks/{task_id}/reviews", response_model=TaskOut)
async def review_task(
    task_id: int,
    body: TaskReviewCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskReviewService = Depends(get_review_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "review")),
) -> Any:
    """上架审核：批准时原子托管发布者奖励；余额不足 409 且保持待审核。"""
    result = await service.review_task(
        actor=current_user,
        task_id=task_id,
        data=body,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action=f"task.review.{body.decision}",
            resource_type="task",
            resource_id=str(task_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"decision": body.decision, "note": body.note},
            **get_client_meta(request),
        )
    return result


@router.post("/task-submissions/{submission_id}/reviews", response_model=TaskClaimOut)
async def review_submission(
    submission_id: int,
    body: SubmissionReviewCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskReviewService = Depends(get_review_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "accept")),
) -> Any:
    """成果验收：通过全额支付给锁定队长；驳回写入返工截止时间。"""
    result = await service.review_submission(
        actor=current_user,
        submission_id=submission_id,
        data=body,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action=f"task.submission.{body.decision}",
            resource_type="task_submission",
            resource_id=str(submission_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"decision": body.decision, "note": body.note},
            **get_client_meta(request),
        )
    return result


@router.post("/tasks/{task_id}/force-close", response_model=TaskOut)
async def force_close_task(
    task_id: int,
    body: ForceCloseCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskReviewService = Depends(get_review_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "close")),
) -> Any:
    result = await service.force_close(
        actor=current_user,
        task_id=task_id,
        reason=body.reason,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="task.force_close",
            resource_type="task",
            resource_id=str(task_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"reason": body.reason},
            **get_client_meta(request),
        )
    return result
