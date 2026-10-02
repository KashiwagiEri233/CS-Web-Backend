"""任务 API：公开浏览 / 认领 / 我的任务 + 管理员 CRUD / 审核。

TOOLS-GOV Slice B（2026-09-14）：解除模块级 mypy 忽略指令，路由对齐 service
真实实现——admin 待审核/通过/驳回改调 ``pending_claims``/``review_claim``（原
调用不存在的 list_claims/approve_claim/reject_claim，必 500）；``_claim_out``
改用既有 ``TaskClaimOut``（原手写 dict 丢 display_name/completed_at/reviewed_by/
review_note）；submit 由 GET 改 POST（前端 BFF 语义）；补齐 publish/close/
取消认领路由（service 方法早已存在但从未暴露）。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import get_current_active_user
from app.dependencies_services import get_task_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.tools import TaskClaimOut, TaskInput, TaskOut
from app.services.task_service import TaskService

router = APIRouter()


class SubmitProofIn(BaseModel):
    """完成提交的可选证明材料链接（TOOLS-GOV Slice E 落库）。"""

    submission_url: Optional[str] = Field(default=None, max_length=500)
    model_config = ConfigDict(str_strip_whitespace=True)


def _task_out(task) -> dict:
    return TaskOut.model_validate(task).model_dump()


def _claim_out(claim) -> dict:
    return TaskClaimOut.model_validate(claim).model_dump()


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


@router.post("/tasks/{task_id}/claim", response_model=TaskClaimOut)
async def claim_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return _claim_out(await service.claim_task(current_user.id, task_id))


@router.delete("/tasks/{task_id}/claim", status_code=204)
async def cancel_claim(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """按任务维度取消本人认领（BFF 以 taskId 发起）。"""
    await service.cancel_task_claim(current_user.id, task_id)


@router.get("/tasks/claimed/me")
async def my_claims(
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return {
        "claims": [_claim_out(c) for c in await service.user_claims(current_user.id)]
    }


@router.get("/tasks/claims/me")
async def my_claims_alias(
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """``/tasks/claimed/me`` 的等价别名（前端 BFF 使用本路径）。"""
    return {
        "claims": [_claim_out(c) for c in await service.user_claims(current_user.id)]
    }


@router.post("/tasks/claims/{claim_id}/submit", response_model=TaskClaimOut)
async def submit_proof(
    claim_id: int,
    body: Optional[SubmitProofIn] = None,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """用户提交完成（认领 → submitted），可选携带证明材料链接（Slice E 落库）。

    注：BFF 还会发送 note 字段，暂无落点（claim_note 语义属认领备注），保持忽略。
    """
    return _claim_out(
        await service.submit_claim(
            current_user.id, claim_id, body.submission_url if body else None
        )
    )


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


@router.post("/admin/tasks/{task_id}/publish", response_model=dict)
async def publish_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "update")),
) -> Any:
    return _task_out(await service.publish_task(task_id))


@router.post("/admin/tasks/{task_id}/close", response_model=dict)
async def close_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "update")),
) -> Any:
    return _task_out(await service.close_task(task_id))


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
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "review")),
) -> Any:
    claims = await service.pending_claims()
    return {"items": [_claim_out(c) for c in claims], "total": len(claims)}


@router.post("/admin/tasks/claims/{claim_id}/approve", response_model=TaskClaimOut)
async def approve_claim(
    claim_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "review")),
) -> Any:
    """通过认领（触发积分联动，见 service.review_claim）。"""
    return _claim_out(await service.review_claim(current_user.id, claim_id, True, None))


@router.post("/admin/tasks/claims/{claim_id}/reject", response_model=TaskClaimOut)
async def reject_claim(
    claim_id: int,
    reason: Optional[str] = None,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "review")),
) -> Any:
    return _claim_out(
        await service.review_claim(current_user.id, claim_id, False, reason)
    )
