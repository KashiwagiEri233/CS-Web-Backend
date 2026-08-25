"""工具集仓储：考试 / 资源 / 任务 / 积分 / 组件注册表。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.component_registry import (
    ComponentRegistryGuide,
    ComponentRegistryItem,
    ComponentRegistryVariant,
)
from app.models.exam import Exam, ExamAttempt, ExamQuestion, ExamQuestionOption
from app.models.points import PointsTransaction
from app.models.resource import Resource
from app.models.task import Task, TaskClaim
from app.repositories.base import dml_rowcount
from app.repositories.base import paginate
from app.core.query_helpers import jsonb_contains


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


class ResourceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_resources(
        self,
        *,
        status: Optional[str] = None,
        resource_type: Optional[str] = None,
        tag: Optional[str] = None,
        submitted_by: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Resource], int]:
        conditions = []
        if status:
            conditions.append(Resource.status == status)
        if resource_type:
            conditions.append(Resource.resource_type == resource_type)
        if tag and tag.strip():
            # 2026-08-10 修复：Resource.tech_tags 为 JSON().with_variant(JSONB())（Variant），
            # contains 退化成字符串 LIKE 且实际调用报错；type_coerce(JSONB) 走 @> 包含。
            conditions.append(jsonb_contains(Resource.tech_tags, [tag.strip()]))
        if submitted_by:
            conditions.append(Resource.submitted_by == submitted_by)
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Resource).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(Resource).where(*conditions).order_by(Resource.created_at.desc()),
            skip,
            limit,
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, resource_id: int) -> Optional[Resource]:
        return await self.db.get(Resource, resource_id)

    async def create(self, data: dict) -> Resource:
        obj = Resource(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, resource: Resource, data: dict) -> None:
        for key, value in data.items():
            setattr(resource, key, value)

    async def delete(self, resource_id: int) -> bool:
        obj = await self.get_by_id(resource_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def increment_view(self, resource_id: int) -> None:
        await self.db.execute(
            update(Resource)
            .where(Resource.id == resource_id)
            .values(view_count=Resource.view_count + 1)
        )


class TaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_tasks(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Task], int]:
        conditions = []
        if status:
            conditions.append(Task.status == status)
        if category:
            conditions.append(Task.category == category)
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Task).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(Task).where(*conditions).order_by(Task.created_at.desc()),
            skip,
            limit,
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, task_id: int) -> Optional[Task]:
        return await self.db.get(Task, task_id)

    async def create(self, data: dict) -> Task:
        obj = Task(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, task: Task, data: dict) -> None:
        for key, value in data.items():
            setattr(task, key, value)

    async def delete(self, task_id: int) -> bool:
        obj = await self.get_by_id(task_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def count_active_claims(self, task_id: int) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(TaskClaim)
                    .where(
                        TaskClaim.task_id == task_id,
                        TaskClaim.status.in_(["claimed", "submitted"]),
                    )
                )
            ).scalar_one()
        )

    async def get_claim(self, task_id: int, user_id: int) -> Optional[TaskClaim]:
        stmt = select(TaskClaim).where(
            TaskClaim.task_id == task_id, TaskClaim.user_id == user_id
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def get_claim_by_id(self, claim_id: int) -> Optional[TaskClaim]:
        return await self.db.get(TaskClaim, claim_id)

    async def create_claim(self, data: dict) -> TaskClaim:
        obj = TaskClaim(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def list_claims_for_task(self, task_id: int) -> list[TaskClaim]:
        stmt = (
            select(TaskClaim)
            .where(TaskClaim.task_id == task_id)
            .order_by(TaskClaim.created_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_claims_for_user(self, user_id: int) -> list[TaskClaim]:
        stmt = (
            select(TaskClaim)
            .where(TaskClaim.user_id == user_id)
            .order_by(TaskClaim.created_at.desc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_pending_claims(self) -> list[TaskClaim]:
        stmt = (
            select(TaskClaim)
            .where(TaskClaim.status == "submitted")
            .order_by(TaskClaim.created_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())


class PointsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def last_balance(self, user_id: int) -> int:
        stmt = (
            select(PointsTransaction.balance_after)
            .where(PointsTransaction.user_id == user_id)
            .order_by(PointsTransaction.created_at.desc(), PointsTransaction.id.desc())
            .limit(1)
        )
        value = (await self.db.execute(stmt)).scalar_one_or_none()
        return int(value or 0)

    async def create_transaction(
        self,
        *,
        user_id: int,
        amount: int,
        reason: str,
        source_type: str,
        source_id,
        balance_after: int,
    ) -> PointsTransaction:
        obj = PointsTransaction(
            user_id=user_id,
            amount=amount,
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            balance_after=balance_after,
        )
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def list_transactions(
        self, user_id: int, limit: int = 50
    ) -> list[PointsTransaction]:
        stmt = (
            select(PointsTransaction)
            .where(PointsTransaction.user_id == user_id)
            .order_by(PointsTransaction.created_at.desc())
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def leaderboard(self, top_n: int = 20) -> list[tuple[int, int]]:
        """(user_id, balance) 按余额倒序。"""
        subq = (
            select(
                PointsTransaction.user_id,
                func.max(PointsTransaction.balance_after).label("balance"),
            )
            .group_by(PointsTransaction.user_id)
            .subquery()
        )
        stmt = (
            select(subq.c.user_id, subq.c.balance)
            .order_by(subq.c.balance.desc())
            .limit(top_n)
        )
        rows = await self.db.execute(stmt)
        return [(int(uid), int(balance)) for uid, balance in rows.all()]


class ComponentRegistryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_items(self) -> list[ComponentRegistryItem]:
        stmt = select(ComponentRegistryItem).order_by(
            ComponentRegistryItem.sort_order.asc(), ComponentRegistryItem.id.asc()
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_item(self, item_id: int) -> Optional[ComponentRegistryItem]:
        return await self.db.get(ComponentRegistryItem, item_id)

    async def get_item_by_slug(self, slug: str) -> Optional[ComponentRegistryItem]:
        stmt = select(ComponentRegistryItem).where(ComponentRegistryItem.slug == slug)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def create_item(self, data: dict) -> ComponentRegistryItem:
        obj = ComponentRegistryItem(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete_item(self, item_id: int) -> bool:
        obj = await self.get_item(item_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def list_variants(self, item_id: int) -> list[ComponentRegistryVariant]:
        stmt = (
            select(ComponentRegistryVariant)
            .where(ComponentRegistryVariant.item_id == item_id)
            .order_by(ComponentRegistryVariant.id.asc())
            # 批量 update/upsert 后强制从 DB 重新读取，避免 identity-map 缓存旧值。
            .execution_options(populate_existing=True)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_variant(
        self, item_id: int, variant_id: int
    ) -> Optional[ComponentRegistryVariant]:
        stmt = select(ComponentRegistryVariant).where(
            ComponentRegistryVariant.id == variant_id,
            ComponentRegistryVariant.item_id == item_id,
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def replace_variants(self, item_id: int, variants: list[dict]) -> None:
        # 先整体禁用该 item 所有变体，保留主键稳定（避免前端列表 key 抖动）。
        await self.db.execute(
            update(ComponentRegistryVariant)
            .where(ComponentRegistryVariant.item_id == item_id)
            .values(is_enabled=False)
        )
        if not variants:
            await self.db.flush()
            return
        # 批量 upsert：以 (item_id, size, color, state) 唯一约束为冲突键，
        # 已存在的行更新 is_enabled，不存在的行插入。一次语句完成，避免逐条 SELECT+UPDATE 的 N 次查询。
        stmt = postgresql.insert(ComponentRegistryVariant).values(
            [
                {
                    "item_id": item_id,
                    "size": v.get("size", ""),
                    "color": v.get("color", ""),
                    "state": v.get("state", ""),
                    "is_enabled": bool(v.get("is_enabled", True)),
                }
                for v in variants
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["item_id", "size", "color", "state"],
            set_={"is_enabled": stmt.excluded.is_enabled},
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def toggle_variant(self, variant_id: int, enabled: bool) -> bool:
        result = await self.db.execute(
            update(ComponentRegistryVariant)
            .where(ComponentRegistryVariant.id == variant_id)
            .values(is_enabled=enabled)
        )
        return dml_rowcount(result) > 0

    async def apply_variant_preset(
        self, item_id: int, preset: str
    ) -> list[ComponentRegistryVariant]:
        """应用变体矩阵预设：按 preset 规则计算各变体的 is_enabled，复用批量 upsert 写回。

        不增删变体，仅翻转 is_enabled；矩阵维度来自已存在的变体集合。
        """
        variants = await self.list_variants(item_id)
        if not variants:
            return []
        updated = [
            {
                "size": v.size,
                "color": v.color,
                "state": v.state,
                "is_enabled": _preset_enabled(preset, v.size, v.color, v.state),
            }
            for v in variants
        ]
        await self.replace_variants(item_id, updated)
        return await self.list_variants(item_id)

    async def get_guide(self, item_id: int) -> Optional[ComponentRegistryGuide]:
        stmt = select(ComponentRegistryGuide).where(
            ComponentRegistryGuide.item_id == item_id
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def upsert_guide(
        self, item_id: int, use_cases: list, anti_patterns: list
    ) -> ComponentRegistryGuide:
        guide = await self.get_guide(item_id)
        if guide is None:
            guide = ComponentRegistryGuide(
                item_id=item_id, use_cases=use_cases, anti_patterns=anti_patterns
            )
            self.db.add(guide)
        else:
            guide.use_cases = use_cases
            guide.anti_patterns = anti_patterns
            guide.updated_at = now_utc()
        await self.db.flush()
        return guide


def _preset_enabled(preset: str, size: str, color: str, state: str) -> bool:
    """预设规则：基于 size/color/state 计算单个变体是否启用。"""
    if preset == "all":
        return True
    if preset == "none":
        return False
    if preset == "primary":
        # 仅主色启用，其余关闭
        return color == "primary"
    if preset == "minimal":
        # 最小可用集：主色 + 默认态 + 中号
        return color == "primary" and state == "default" and size == "md"
    # 未知预设：保持原样（交给上层校验，这里兜底为启用）
    return True
