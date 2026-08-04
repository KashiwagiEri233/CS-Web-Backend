"""工具集 API：考试（公开答题/我的成绩 + 管理员组卷）、资源、任务、积分、Auxilio、组件注册表。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import re

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.core.exceptions import NotFoundException, ValidationException
from app.dependencies import get_current_active_user
from app.dependencies_services import (
    get_auxilio_service,
    get_component_registry_service,
    get_exam_service,
    get_points_service,
    get_resource_service,
    get_task_service,
)
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.tools import (
    ComponentGuideInput,
    ComponentItemInput,
    ComponentVariantInput,
    ExamInput,
    ExamSubmitIn,
    QuestionInput,
    ResourceInput,
    TaskInput,
)
from app.services.auxilio_service import AuxilioService
from app.services.component_registry_service import ComponentRegistryService
from app.services.exam_service import ExamService
from app.services.points_service import PointsService
from app.services.resource_service import ResourceService
from app.services.task_service import TaskService

router = APIRouter()

RESOURCE_FILE_MAX_SIZE = 10 * 1024 * 1024
RESOURCE_ALLOWED_MIME = {
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/markdown",
}
_RESOURCE_FILES_DIR = Path("data") / "resource-files"
_FILENAME_RE = re.compile(r"^[a-f0-9-]+-\d+\.\w+$")


def _exam_out(exam) -> dict:
    from app.schemas.tools import ExamOut

    return ExamOut.model_validate(exam).model_dump()


def _question_out(q, include_answer: bool = False) -> dict:
    def _opt_get(opt, key):
        return opt.get(key) if isinstance(opt, dict) else getattr(opt, key, None)

    options = []
    for opt in getattr(q, "options", []) or []:
        item = {
            "label": _opt_get(opt, "label"),
            "content": _opt_get(opt, "content"),
            "sort_order": _opt_get(opt, "sort_order"),
        }
        if include_answer:
            item["is_correct"] = _opt_get(opt, "is_correct")
        options.append(item)
    return {
        "id": q.id,
        "exam_id": q.exam_id,
        "type": q.type,
        "title": q.title,
        "content_markdown": q.content_markdown,
        "score": q.score,
        "sort_order": q.sort_order,
        "options": options,
        "created_at": q.created_at,
    }


def _resource_out(r) -> dict:
    from app.schemas.tools import ResourceOut

    data = ResourceOut.model_validate(r).model_dump()
    data["submitted_by_name"] = getattr(r, "submitted_by_name", None)
    return data


def _task_out(task) -> dict:
    from app.schemas.tools import TaskOut

    return TaskOut.model_validate(task).model_dump()


def _claim_out(claim) -> dict:
    return {
        "id": claim.id,
        "task_id": claim.task_id,
        "user_id": claim.user_id,
        "display_name": getattr(claim, "display_name", None),
        "status": claim.status,
        "claim_note": claim.claim_note,
        "completed_at": claim.completed_at,
        "reviewed_by": claim.reviewed_by,
        "review_note": claim.review_note,
        "created_at": claim.created_at,
    }


# ------------------------------------------------------------------ 考试（公开）


@router.get("/exam", response_model=PaginatedResponse[dict])
async def list_exams(
    pagination: PaginationParams = Depends(),
    status: Optional[str] = "published",
    tag: Optional[str] = None,
    service: ExamService = Depends(get_exam_service),
) -> Any:
    exams, total = await service.list_exams(
        status=status, tag=tag, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[_exam_out(e) for e in exams],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/exam/{exam_id}")
async def get_exam(
    exam_id: int,
    service: ExamService = Depends(get_exam_service),
) -> Any:
    return _exam_out(await service.get_exam(exam_id))


@router.get("/exam/{exam_id}/questions")
async def list_exam_questions(
    exam_id: int,
    service: ExamService = Depends(get_exam_service),
) -> Any:
    questions = await service.list_questions(exam_id)
    return {"questions": [_question_out(q) for q in questions]}


@router.post("/exam/{exam_id}/submit")
async def submit_answers(
    exam_id: int,
    body: ExamSubmitIn,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    results = []
    for item in body.answers:
        results.append(
            await service.submit_answer(
                current_user.id, exam_id, item.question_id, item.answer
            )
        )
    return {
        "results": results,
        "score": sum(r.get("score") or 0 for r in results),
    }


@router.get("/exam/{exam_id}/my-results")
async def my_results(
    exam_id: int,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    attempts = await service.user_attempts(current_user.id, exam_id)
    total_score = sum(a["score"] or 0 for a in attempts)
    return {"attempts": attempts, "total_score": total_score}


# ------------------------------------------------------------------ 考试（管理）


@router.get("/admin/exam")
async def admin_list_exams(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "read")),
) -> Any:
    exams, total = await service.list_exams(status=status, skip=skip, limit=limit)
    return {"items": [_exam_out(e) for e in exams], "total": total}


@router.post("/admin/exam", response_model=dict, status_code=201)
async def create_exam(
    body: ExamInput,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "create")),
) -> Any:
    return _exam_out(await service.create_exam(current_user.id, body))


@router.get("/admin/exam/{exam_id}/ranking")
async def exam_ranking(
    exam_id: int,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "read")),
) -> Any:
    return {"ranking": await service.exam_ranking(exam_id)}


@router.put("/admin/exam/{exam_id}", response_model=dict)
async def update_exam(
    exam_id: int,
    body: ExamInput,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "update")),
) -> Any:
    return _exam_out(await service.update_exam(exam_id, body))


@router.delete("/admin/exam/{exam_id}")
async def delete_exam(
    exam_id: int,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "delete")),
) -> Any:
    await service.delete_exam(exam_id)
    return {"ok": True}


@router.post("/admin/exam/{exam_id}/publish", response_model=dict)
async def publish_exam(
    exam_id: int,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "publish")),
) -> Any:
    return _exam_out(await service.publish_exam(exam_id))


@router.post("/admin/exam/{exam_id}/end", response_model=dict)
async def end_exam(
    exam_id: int,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "end")),
) -> Any:
    return _exam_out(await service.end_exam(exam_id))


@router.get("/admin/exam/{exam_id}/questions")
async def admin_list_questions(
    exam_id: int,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "read")),
) -> Any:
    questions = await service.list_questions(exam_id)
    return {"questions": [_question_out(q, include_answer=True) for q in questions]}


@router.post("/admin/exam/{exam_id}/questions", response_model=dict, status_code=201)
async def create_question(
    exam_id: int,
    body: QuestionInput,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "question_create")),
) -> Any:
    return _question_out(
        await service.create_question(exam_id, body), include_answer=True
    )


@router.put("/admin/exam/{exam_id}/questions/{question_id}", response_model=dict)
async def update_question(
    exam_id: int,
    question_id: int,
    body: QuestionInput,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "question_update")),
) -> Any:
    return _question_out(
        await service.update_question(question_id, body), include_answer=True
    )


@router.delete("/admin/exam/{exam_id}/questions/{question_id}")
async def delete_question(
    exam_id: int,
    question_id: int,
    service: ExamService = Depends(get_exam_service),
    current_user: User = Depends(require_permission("exam", "question_delete")),
) -> Any:
    await service.delete_question(question_id)
    return {"ok": True}


# ------------------------------------------------------------------ 资源


@router.get("/resource")
async def list_resources(
    resource_type: Optional[str] = None,
    tag: Optional[str] = None,
    status: str = "approved",
    skip: int = 0,
    limit: int = 20,
    service: ResourceService = Depends(get_resource_service),
) -> Any:
    resources, total = await service.list_resources(
        status=status, resource_type=resource_type, tag=tag, skip=skip, limit=limit
    )
    return {"items": [_resource_out(r) for r in resources], "total": total}


@router.get("/resource/{resource_id}")
async def get_resource(
    resource_id: int,
    service: ResourceService = Depends(get_resource_service),
) -> Any:
    resource = await service.get_resource(resource_id)
    await service.increment_view(resource_id)
    return _resource_out(resource)


@router.post("/resource", response_model=dict, status_code=201)
async def create_resource(
    body: ResourceInput,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return _resource_out(await service.create_resource(current_user.id, body))


@router.post("/resource/upload")
async def upload_resource_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    content = await file.read()
    if len(content) > RESOURCE_FILE_MAX_SIZE:
        raise ValidationException(
            message="文件大小不能超过 10MB", error_code="FILE_TOO_LARGE"
        )
    ext = Path(file.filename or "").suffix.lower()
    if not ext or ext not in {
        ".pdf",
        ".zip",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".txt",
        ".md",
    }:
        raise ValidationException(
            message="文件类型不被允许", error_code="INVALID_FILE_TYPE"
        )
    _RESOURCE_FILES_DIR.mkdir(parents=True, exist_ok=True)
    import time

    filename = f"{current_user.id}-{int(time.time() * 1000)}{ext}"
    try:
        (_RESOURCE_FILES_DIR / filename).write_bytes(content)
    except OSError as exc:
        raise ValidationException(
            message="文件保存失败", error_code="FILE_SAVE_FAILED"
        ) from exc
    return {"fileUrl": f"/api/tools/resource/files/{filename}"}


@router.get("/resource/files/{filename}")
async def serve_resource_file(filename: str) -> Any:
    if not _FILENAME_RE.match(filename):
        raise NotFoundException(
            message="文件不存在", resource_type="resource_file", resource_id=filename
        )
    path = _RESOURCE_FILES_DIR / filename
    if not path.is_file():
        raise NotFoundException(
            message="文件不存在", resource_type="resource_file", resource_id=filename
        )
    from fastapi.responses import FileResponse

    return FileResponse(path)


@router.post("/admin/resource")
async def review_resource(
    body: dict,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "review")),
) -> Any:
    """资源审核：{resource_id, action: approve|reject, note?}。"""
    resource_id = body.get("resource_id")
    action = body.get("action")
    if not resource_id or action not in {"approve", "reject"}:
        raise ValidationException(message="参数不合法", error_code="VALIDATION_FAILED")
    resource = await service.review_resource(
        current_user.id, int(resource_id), action == "approve", body.get("note")
    )
    return _resource_out(resource)


# ------------------------------------------------------------------ 任务


@router.get("/task")
async def list_tasks(
    status: Optional[str] = None,
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    service: TaskService = Depends(get_task_service),
) -> Any:
    tasks, total = await service.list_tasks(
        status=status, category=category, skip=skip, limit=limit
    )
    return {"items": [_task_out(t) for t in tasks], "total": total}


@router.get("/task/{task_id}")
async def get_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
) -> Any:
    return _task_out(await service.get_task(task_id))


@router.get("/task/{task_id}/claims")
async def task_claims(
    task_id: int,
    service: TaskService = Depends(get_task_service),
) -> Any:
    claims = await service.task_claims(task_id)
    return {"claims": [_claim_out(c) for c in claims]}


@router.post("/task/{task_id}/claim", response_model=dict, status_code=201)
async def claim_task(
    task_id: int,
    body: Optional[dict] = None,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    note = (body or {}).get("note")
    return _claim_out(await service.claim_task(current_user.id, task_id, note))


@router.post("/task/claims/{claim_id}/submit")
async def submit_claim(
    claim_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return _claim_out(await service.submit_claim(current_user.id, claim_id))


@router.delete("/task/claims/{claim_id}")
async def cancel_claim(
    claim_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    await service.cancel_claim(current_user.id, claim_id)
    return {"ok": True}


@router.get("/task/claims/mine")
async def my_claims(
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    claims = await service.user_claims(current_user.id)
    return {"claims": [_claim_out(c) for c in claims]}


@router.post("/admin/task", response_model=dict, status_code=201)
async def create_task(
    body: TaskInput,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "create")),
) -> Any:
    return _task_out(await service.create_task(current_user.id, body))


@router.put("/admin/task/{task_id}", response_model=dict)
async def update_task(
    task_id: int,
    body: TaskInput,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "update")),
) -> Any:
    return _task_out(await service.update_task(task_id, body))


@router.delete("/admin/task/{task_id}")
async def delete_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "delete")),
) -> Any:
    await service.delete_task(task_id)
    return {"ok": True}


@router.post("/admin/task/{task_id}/publish", response_model=dict)
async def publish_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "publish")),
) -> Any:
    return _task_out(await service.publish_task(task_id))


@router.post("/admin/task/{task_id}/close", response_model=dict)
async def close_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "close")),
) -> Any:
    return _task_out(await service.close_task(task_id))


@router.get("/admin/task/claims/pending")
async def pending_claims(
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "claim_review")),
) -> Any:
    claims = await service.pending_claims()
    return {"claims": [_claim_out(c) for c in claims]}


@router.post("/admin/task/claims/{claim_id}/review")
async def review_claim(
    claim_id: int,
    body: dict,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(require_permission("task", "claim_review")),
) -> Any:
    """认领审核：{approved: bool, note?}。"""
    approved = bool(body.get("approved"))
    claim = await service.review_claim(
        current_user.id, claim_id, approved, body.get("note")
    )
    return _claim_out(claim)


# ------------------------------------------------------------------ 积分


@router.get("/points")
async def my_points(
    service: PointsService = Depends(get_points_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.profile(current_user.id)


@router.get("/points/leaderboard")
async def leaderboard(
    top_n: int = 20,
    service: PointsService = Depends(get_points_service),
) -> Any:
    return {"leaderboard": await service.leaderboard(top_n)}


# ------------------------------------------------------------------ Auxilio


@router.get("/auxilio")
async def auxilio_analysis(
    service: AuxilioService = Depends(get_auxilio_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.analyze_learning_profile(current_user.id)


# ------------------------------------------------------------------ 组件注册表


@router.get("/component-registry")
async def list_components(
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return {"components": await service.list_components()}


@router.get("/component-registry/{item_id}")
async def get_component(
    item_id: int,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return await service.get_component(item_id)


@router.post("/component-registry", response_model=dict, status_code=201)
async def create_component(
    body: ComponentItemInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.create_component(body)


@router.put("/component-registry/{item_id}")
async def update_component(
    item_id: int,
    body: ComponentItemInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.update_component(item_id, body)


@router.delete("/component-registry/{item_id}")
async def delete_component(
    item_id: int,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    await service.delete_component(item_id)
    return {"ok": True}


@router.put("/component-registry/{item_id}/variants")
async def replace_variants(
    item_id: int,
    body: list[ComponentVariantInput],
    service: ComponentRegistryService = Depends(get_component_registry_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.replace_variants(item_id, body)


@router.post("/component-registry/{item_id}/variants/{variant_id}/toggle")
async def toggle_variant(
    item_id: int,
    variant_id: int,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    body = await _try_json(request)
    return await service.toggle_variant(
        item_id, variant_id, bool(body.get("enabled", True))
    )


async def _try_json(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:  # noqa: BLE001
        return {}


@router.put("/component-registry/{item_id}/guide")
async def update_guide(
    item_id: int,
    body: ComponentGuideInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.update_guide(item_id, body)
