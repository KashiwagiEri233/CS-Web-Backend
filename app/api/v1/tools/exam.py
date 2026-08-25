"""考试 API：公开答题 / 我的成绩 + 管理员组卷。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends

from app.dependencies import get_current_active_user
from app.dependencies_services import get_exam_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.tools import ExamInput, ExamSubmitIn, ExamOut, QuestionInput
from app.services.exam_service import ExamService

router = APIRouter()


def _exam_out(exam) -> dict:
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


# ------------------------------------------------------------------ 公开


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


# ------------------------------------------------------------------ 管理


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
