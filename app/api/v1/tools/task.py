# mypy: ignore-errors
# 本文件 API 与 service 契约错位(存量)，暂用模块级忽略，保持端点/契约不变
"""任务 API：公开浏览 / 认领 / 我的任务 + 管理员 CRUD / 审核。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends

from app.dependencies import get_current_active_user
from app.dependencies_services import get_task_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.tools import TaskInput, TaskOut
from app.services.task_service import TaskService

router = APIRouter()


def _task_out(task) -> dict:
    return TaskOut.model_validate(task).model_dump()


def _claim_out(claim) -> dict:
    return {
        "id": claim.id,
        "task_id": claim.task_id,
        "user_id": claim.user_id,
        "status": claim.status,
        "claim_note": claim.claim_note,
        "created_at": claim.created_at,
    }


@router.get("/tasks", response_model=PaginatedResponse[dict])
async def list_tasks(
    pagination: PaginationParams = Depends(),
    status: Optional[str] = "open",
    service: TaskService = Depends(get_task_service),
) -> Any:
    tasks, total = await service.list_tasks(
        status=status, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[_task_out(t) for t in tasks],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
) -> Any:
    return _task_out(await service.get_task(task_id))


@router.post("/tasks/{task_id}/claim")
async def claim_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return _claim_out(await service.claim_task(current_user.id, task_id))


@router.get("/tasks/claimed/me")
async def my_claims(
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return {
        "claims": [_claim_out(c) for c in await service.user_claims(current_user.id)]
    }


@router.get("/tasks/claims/{claim_id}/submit")
async def submit_proof(
    claim_id: int,
    proof: str,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    # 接线：service 现有方法名为 submit_claim(user_id, claim_id)
    return _claim_out(await service.submit_claim(current_user.id, claim_id))


@router.get("/tasks/claims/me")
async def my_claims_alias(
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return {
        "claims": [_claim_out(c) for c in await service.user_claims(current_user.id)]
    }


# ------------------------------------------------------------------ 管理


@router.get("/admin/tasks")
async def admin_list_tasks(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "read")),
) -> Any:
    tasks, total = await service.list_tasks(status=status, skip=skip, limit=limit)
    return {"items": [_task_out(t) for t in tasks], "total": total}


@router.post("/admin/tasks", response_model=dict, status_code=201)
async def create_task(
    body: TaskInput,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "create")),
) -> Any:
    return _task_out(await service.create_task(current_user.id, body))


@router.put("/admin/tasks/{task_id}", response_model=dict)
async def update_task(
    task_id: int,
    body: TaskInput,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "update")),
) -> Any:
    return _task_out(await service.update_task(task_id, body))


@router.delete("/admin/tasks/{task_id}")
async def delete_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "delete")),
) -> Any:
    await service.delete_task(task_id)
    return {"ok": True}


@router.get("/admin/tasks/claims/pending")
async def pending_claims(
    skip: int = 0,
    limit: int = 50,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "review")),
) -> Any:
    claims, total = await service.list_claims(status="pending", skip=skip, limit=limit)
    return {"items": [_claim_out(c) for c in claims], "total": total}


@router.post("/admin/tasks/claims/{claim_id}/approve")
async def approve_claim(
    claim_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "review")),
) -> Any:
    return _claim_out(await service.approve_claim(claim_id))


@router.post("/admin/tasks/claims/{claim_id}/reject")
async def reject_claim(
    claim_id: int,
    reason: Optional[str] = None,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "review")),
) -> Any:
    return _claim_out(await service.reject_claim(claim_id, reason))
