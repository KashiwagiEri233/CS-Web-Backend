"""考试仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.exam import Exam, ExamAttempt, ExamQuestion, ExamQuestionOption
from app.core.query_helpers import jsonb_contains
from app.repositories.base import paginate


class ExamRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_exams(
        self,
        *,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Exam], int]:
        conditions = []
        if status:
            conditions.append(Exam.status == status)
        if tag and tag.strip():
            # 2026-08-10 修复：Exam.tech_tags 为 JSON().with_variant(JSONB())（Variant），
            # contains 退化成字符串 LIKE 且实际调用报错；type_coerce(JSONB) 走 @> 包含。
            conditions.append(jsonb_contains(Exam.tech_tags, [tag.strip()]))
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Exam).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(Exam).where(*conditions).order_by(Exam.created_at.desc()),
            skip,
            limit,
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, exam_id: int) -> Optional[Exam]:
        return await self.db.get(Exam, exam_id)

    async def create(self, data: dict) -> Exam:
        obj = Exam(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, exam: Exam, data: dict) -> None:
        for key, value in data.items():
            setattr(exam, key, value)

    async def delete(self, exam_id: int) -> bool:
        obj = await self.get_by_id(exam_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def list_questions(self, exam_id: int) -> list[ExamQuestion]:
        stmt = (
            select(ExamQuestion)
            .where(ExamQuestion.exam_id == exam_id)
            .order_by(ExamQuestion.sort_order.asc(), ExamQuestion.id.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_question(
        self, question_id: int, exam_id: int
    ) -> Optional[ExamQuestion]:
        stmt = select(ExamQuestion).where(
            ExamQuestion.id == question_id, ExamQuestion.exam_id == exam_id
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def update_question(self, question: ExamQuestion, data: dict) -> None:
        for key, value in data.items():
            setattr(question, key, value)

    async def create_question(self, data: dict) -> ExamQuestion:
        obj = ExamQuestion(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete_question(self, question_id: int) -> bool:
        obj = await self.db.get(ExamQuestion, question_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def list_options(self, question_id: int) -> list[ExamQuestionOption]:
        stmt = (
            select(ExamQuestionOption)
            .where(ExamQuestionOption.question_id == question_id)
            .order_by(ExamQuestionOption.sort_order.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def replace_options(self, question_id: int, options: list[dict]) -> None:
        await self.db.execute(
            update(ExamQuestionOption)
            .where(ExamQuestionOption.question_id == question_id)
            .values(is_correct=False)
        )
        for i, opt in enumerate(options):
            existing: Optional[ExamQuestionOption] = (
                await self.db.execute(
                    select(ExamQuestionOption).where(
                        ExamQuestionOption.question_id == question_id,
                        ExamQuestionOption.label == opt.get("label", ""),
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.content = opt.get("content", "")
                existing.is_correct = bool(opt.get("is_correct", False))
                existing.sort_order = i
            else:
                self.db.add(
                    ExamQuestionOption(
                        question_id=question_id,
                        label=opt.get("label", ""),
                        content=opt.get("content", ""),
                        is_correct=bool(opt.get("is_correct", False)),
                        sort_order=i,
                    )
                )
        await self.db.flush()

    async def get_attempt(
        self, user_id: int, question_id: int
    ) -> Optional[ExamAttempt]:
        stmt = select(ExamAttempt).where(
            ExamAttempt.user_id == user_id, ExamAttempt.question_id == question_id
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def upsert_attempt(
        self,
        user_id: int,
        exam_id: int,
        question_id: int,
        answer: str,
        is_correct,
        score,
    ) -> ExamAttempt:
        attempt = await self.get_attempt(user_id, question_id)
        if attempt is None:
            attempt = ExamAttempt(
                user_id=user_id,
                exam_id=exam_id,
                question_id=question_id,
                answer=answer,
                is_correct=is_correct,
                score=score,
            )
            self.db.add(attempt)
        else:
            attempt.answer = answer
            attempt.is_correct = is_correct
            attempt.score = score
            attempt.submitted_at = now_utc()
        await self.db.flush()
        return attempt

    async def list_user_attempts(self, user_id: int, exam_id: int) -> list[ExamAttempt]:
        stmt = (
            select(ExamAttempt)
            .where(ExamAttempt.user_id == user_id, ExamAttempt.exam_id == exam_id)
            .order_by(ExamAttempt.submitted_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_attempts_for_exam(self, exam_id: int) -> list[ExamAttempt]:
        stmt = (
            select(ExamAttempt)
            .where(ExamAttempt.exam_id == exam_id)
            .order_by(ExamAttempt.submitted_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def first_attempt_at(self, user_id: int, exam_id: int) -> Optional[datetime]:
        stmt = select(func.min(ExamAttempt.submitted_at)).where(
            ExamAttempt.user_id == user_id, ExamAttempt.exam_id == exam_id
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()