"""原生任务 API（P3）：列表、创建编辑、接取、提交、取消与历史。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_client_meta
from app.database import get_db
from app.dependencies_services import get_audit_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.task import (
    ClaimCreate,
    ClaimCancelOut,
    SubmissionCreate,
    TaskActionOut,
    TaskClaimOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from app.services.audit_service import AuditService
from app.services.task.review_service import TaskReviewService
from app.services.task.task_service import TaskService

router = APIRouter()
claim_router = APIRouter()


def get_task_service(db: AsyncSession = Depends(get_db)) -> TaskService:
    return TaskService(db)


def get_review_service(db: AsyncSession = Depends(get_db)) -> TaskReviewService:
    return TaskReviewService(db)


@router.get("", response_model=PaginatedResponse[TaskOut])
async def list_tasks(
    pagination: PaginationParams = Depends(),
    status: Optional[str] = None,
    category: Optional[str] = None,
    keyword: Optional[str] = Query(None, max_length=50),
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "read")),
) -> Any:
    """任务大厅：默认仅 published，按可见范围过滤。"""
    items, total = await service.list_tasks(
        actor=current_user,
        status=status,
        category=category,
        keyword=keyword,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/me/published", response_model=PaginatedResponse[TaskOut])
async def list_my_published(
    pagination: PaginationParams = Depends(),
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "read")),
) -> Any:
    items, total = await service.list_my_published(
        actor=current_user, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/me/claims", response_model=PaginatedResponse[TaskClaimOut])
async def list_my_claims(
    pagination: PaginationParams = Depends(),
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "read")),
) -> Any:
    items, total = await service.list_my_claims(
        actor=current_user, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    body: TaskCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskService = Depends(get_task_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "create")),
) -> Any:
    result = await service.create_task(
        actor=current_user,
        data=body,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="task.create",
            resource_type="task",
            resource_id=str(result.get("id")),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"title": body.title, "reward_total": body.reward_total},
            **get_client_meta(request),
        )
    return result


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "read")),
) -> Any:
    return await service.get_task(actor=current_user, task_id=task_id)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    body: TaskUpdate,
    request: Request,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskService = Depends(get_task_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "update")),
) -> Any:
    result = await service.update_task(
        actor=current_user,
        task_id=task_id,
        data=body,
        if_match=if_match,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="task.update",
            resource_type="task",
            resource_id=str(task_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"fields": sorted(body.model_dump(exclude_unset=True).keys())},
            **get_client_meta(request),
        )
    return result


@router.delete("/{task_id}", response_model=TaskOut)
async def archive_task(
    task_id: int,
    request: Request,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskService = Depends(get_task_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "delete")),
) -> Any:
    """归档草稿/驳回任务；有资金历史的任务必须先关闭。"""
    result = await service.archive_task(
        actor=current_user,
        task_id=task_id,
        if_match=if_match,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="task.archive",
            resource_type="task",
            resource_id=str(task_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            **get_client_meta(request),
        )
    return result


@router.post("/{task_id}/review-requests", response_model=TaskOut)
async def request_task_review(
    task_id: int,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskService = Depends(get_task_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "publish")),
) -> Any:
    result = await service.request_review(
        actor=current_user,
        task_id=task_id,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="task.request_review",
            resource_type="task",
            resource_id=str(task_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            **get_client_meta(request),
        )
    return result


@router.get("/{task_id}/claims", response_model=list[TaskClaimOut])
async def list_task_claims(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "read")),
) -> Any:
    return await service.list_claims(actor=current_user, task_id=task_id)


@router.get("/{task_id}/history", response_model=PaginatedResponse[TaskActionOut])
async def list_task_history(
    task_id: int,
    pagination: PaginationParams = Depends(),
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "read")),
) -> Any:
    rows, total = await service.list_history(
        actor=current_user,
        task_id=task_id,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=rows, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.post("/{task_id}/claims", response_model=TaskClaimOut, status_code=201)
async def claim_task(
    task_id: int,
    request: Request,
    body: Optional[ClaimCreate] = None,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskService = Depends(get_task_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "claim")),
) -> Any:
    result = await service.claim_task(
        actor=current_user,
        task_id=task_id,
        data=body or ClaimCreate(),
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="task.claim",
            resource_type="task",
            resource_id=str(task_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"claim_id": result.get("id"), "team_id": result.get("team_id")},
            **get_client_meta(request),
        )
    return result


@claim_router.post("/{claim_id}/cancel", response_model=ClaimCancelOut)
async def cancel_claim(
    claim_id: int,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskService = Depends(get_task_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "claim")),
) -> Any:
    result = await service.cancel_claim(
        actor=current_user,
        claim_id=claim_id,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="task.claim.cancel",
            resource_type="task_claim",
            resource_id=str(claim_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={"task_status": result.get("task_status")},
            **get_client_meta(request),
        )
    return result


@claim_router.post("/{claim_id}/submissions", response_model=TaskClaimOut, status_code=201)
async def submit_claim(
    claim_id: int,
    body: SubmissionCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: TaskService = Depends(get_task_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("task", "submit")),
) -> Any:
    result = await service.submit_claim(
        actor=current_user,
        claim_id=claim_id,
        data=body,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    if not result.pop("_replayed", False):
        await audit.record_atomic(
            action="task.submit",
            resource_type="task_claim",
            resource_id=str(claim_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={
                "revision": (result.get("submission") or {}).get("revision")
                if isinstance(result.get("submission"), dict)
                else None
            },
            **get_client_meta(request),
        )
    return result
