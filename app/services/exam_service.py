"""考试服务：CRUD / 组卷 / 答题判分 / 排名。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.timezone import now_utc
from app.models.exam import Exam, ExamQuestion
from app.models.user import User
from app.repositories.tools_repo import ExamRepository
from app.schemas.tools import ExamInput, QuestionInput
from app.services.audit_service import AuditService


class ExamService:
    def __init__(self, db: AsyncSession, audit: Optional[AuditService] = None):
        self.db = db
        self.repo = ExamRepository(db)
        self.audit = audit if audit is not None else AuditService()

    # ------------------------------------------------------------------ CRUD

    async def list_exams(
        self,
        *,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Exam], int]:
        return await self.repo.list_exams(
            status=status, tag=tag, skip=skip, limit=limit
        )

    async def get_exam(self, exam_id: int) -> Exam:
        exam = await self.repo.get_by_id(exam_id)
        if exam is None:
            raise NotFoundException(
                message="考试不存在", resource_type="exam", resource_id=str(exam_id)
            )
        return exam

    async def create_exam(self, created_by: int, data: ExamInput) -> Exam:
        payload = data.model_dump()
        payload["created_by"] = created_by
        exam = await self.repo.create(payload)
        await self.db.commit()
        return exam

    async def update_exam(self, exam_id: int, data: ExamInput) -> Exam:
        exam = await self.get_exam(exam_id)
        await self.repo.update(exam, data.model_dump(exclude_unset=True))
        await self.db.commit()
        return exam

    async def publish_exam(self, exam_id: int) -> Exam:
        exam = await self.get_exam(exam_id)
        await self.repo.update(exam, {"status": "published"})
        await self.db.commit()
        return exam

    async def end_exam(self, exam_id: int) -> Exam:
        exam = await self.get_exam(exam_id)
        await self.repo.update(exam, {"status": "ended", "end_time": now_utc()})
        await self.db.commit()
        return exam

    async def delete_exam(self, exam_id: int) -> None:
        if not await self.repo.delete(exam_id):
            raise NotFoundException(
                message="考试不存在", resource_type="exam", resource_id=str(exam_id)
            )
        await self.db.commit()

    # ------------------------------------------------------------------ 题目

    async def list_questions(self, exam_id: int) -> list[ExamQuestion]:
        await self.get_exam(exam_id)
        questions = await self.repo.list_questions(exam_id)
        for q in questions:
            setattr(
                q,
                "options",
                [
                    {
                        "label": o.label,
                        "content": o.content,
                        "is_correct": o.is_correct,
                        "sort_order": o.sort_order,
                    }
                    for o in await self.repo.list_options(q.id)
                ],
            )
        return questions

    async def create_question(self, exam_id: int, data: QuestionInput) -> ExamQuestion:
        await self.get_exam(exam_id)
        payload = data.model_dump(exclude={"options"})
        payload["exam_id"] = exam_id
        question = await self.repo.create_question(payload)
        if data.options:
            await self.repo.replace_options(question.id, data.options)
        await self.db.commit()
        return question

    async def update_question(
        self, question_id: int, data: QuestionInput
    ) -> ExamQuestion:
        question = await self.db.get(ExamQuestion, question_id)
        if question is None:
            raise NotFoundException(
                message="题目不存在",
                resource_type="exam_question",
                resource_id=str(question_id),
            )
        await self.repo.update_question(question, data.model_dump(exclude={"options"}))
        if data.options:
            await self.repo.replace_options(question.id, data.options)
        await self.db.commit()
        return question

    async def delete_question(self, question_id: int) -> None:
        if not await self.repo.delete_question(question_id):
            raise NotFoundException(
                message="题目不存在",
                resource_type="exam_question",
                resource_id=str(question_id),
            )
        await self.db.commit()

    # ------------------------------------------------------------------ 答题

    async def submit_answer(
        self, user_id: int, exam_id: int, question_id: int, answer: str
    ) -> dict:
        exam = await self.get_exam(exam_id)
        if exam.status != "published":
            raise ValidationException(
                message="考试未开放", error_code=ErrorCode.Validation.VALIDATION_FAILED
            )
        now = now_utc()
        if exam.start_time and exam.start_time > now:
            raise ValidationException(
                message="考试尚未开始",
                error_code=ErrorCode.Validation.VALIDATION_FAILED,
            )
        if exam.end_time and exam.end_time < now:
            raise ValidationException(
                message="考试已结束", error_code=ErrorCode.Validation.VALIDATION_FAILED
            )
        if exam.duration_minutes and exam.duration_minutes > 0:
            first = await self.repo.first_attempt_at(user_id, exam_id)
            if first:
                elapsed = (now - first).total_seconds()
                if elapsed > exam.duration_minutes * 60:
                    raise ValidationException(
                        message="答题时间已超时",
                        error_code=ErrorCode.Validation.VALIDATION_FAILED,
                    )

        question = await self.repo.get_question(question_id, exam_id)
        if question is None:
            raise NotFoundException(
                message="题目不属于该考试",
                resource_type="exam_question",
                resource_id=str(question_id),
            )

        is_correct = None
        score = None
        if question.type == "single_choice":
            options = await self.repo.list_options(question.id)
            correct = next((o for o in options if o.is_correct), None)
            is_correct = bool(correct and correct.label == answer)
            score = question.score if is_correct else 0

        attempt = await self.repo.upsert_attempt(
            user_id, exam_id, question_id, answer, is_correct, score
        )
        await self.db.commit()
        return {
            "id": attempt.id,
            "user_id": attempt.user_id,
            "exam_id": attempt.exam_id,
            "question_id": attempt.question_id,
            "answer": attempt.answer,
            "is_correct": attempt.is_correct,
            "score": attempt.score,
            "submitted_at": attempt.submitted_at,
        }

    async def user_attempts(self, user_id: int, exam_id: int) -> list[dict]:
        attempts = await self.repo.list_user_attempts(user_id, exam_id)
        return [
            {
                "id": a.id,
                "user_id": a.user_id,
                "exam_id": a.exam_id,
                "question_id": a.question_id,
                "answer": a.answer,
                "is_correct": a.is_correct,
                "score": a.score,
                "submitted_at": a.submitted_at,
            }
            for a in attempts
        ]

    async def exam_ranking(self, exam_id: int) -> list[dict]:
        await self.get_exam(exam_id)
        attempts = await self.repo.list_attempts_for_exam(exam_id)
        user_map: dict[int, dict] = {}
        for a in attempts:
            entry = user_map.setdefault(
                a.user_id,
                {
                    "user_id": a.user_id,
                    "total_score": 0,
                    "total_questions": 0,
                    "correct_count": 0,
                    "submitted_at": None,
                },
            )
            entry["total_score"] += a.score or 0
            entry["total_questions"] += 1
            if a.is_correct:
                entry["correct_count"] += 1
            if entry["submitted_at"] is None or (
                a.submitted_at and a.submitted_at > entry["submitted_at"]
            ):
                entry["submitted_at"] = a.submitted_at

        user_ids = list(user_map.keys())
        users = {}
        if user_ids:
            users = {
                u.id: u
                for u in (
                    await self.db.execute(select(User).where(User.id.in_(user_ids)))
                )
                .scalars()
                .all()
            }
        result = []
        for entry in sorted(
            user_map.values(), key=lambda e: (-e["total_score"], str(e["submitted_at"]))
        ):
            user = users.get(entry["user_id"])
            result.append(
                {
                    "user_id": entry["user_id"],
                    "display_name": (
                        (user.display_name or user.username) if user else None
                    ),
                    "total_score": entry["total_score"],
                    "total_questions": entry["total_questions"],
                    "correct_count": entry["correct_count"],
                    "submitted_at": entry["submitted_at"],
                }
            )
        return result
