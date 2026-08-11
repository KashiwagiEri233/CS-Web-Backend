"""Phase 5 集成测试：考试/资源/任务/积分/Auxilio/组件注册表（需要 PostgreSQL）。

覆盖：
1. 考试：创建/组卷/发布/答题判分/排名；
2. 资源：提交/审核/浏览；
3. 任务：创建/发布/认领（限额）/提交/审核（积分联动）；
4. 积分：流水/余额/排行榜/等级；
5. Auxilio：薄弱标签 + 资源推荐；
6. 组件注册表：item/variants/guide。
"""

import uuid

import pytest
from sqlalchemy import delete

from app.core.exceptions import ConflictException
from app.database import get_session
from app.models.component_registry import ComponentRegistryItem
from app.models.exam import Exam
from app.models.resource import Resource
from app.models.task import Task
from app.models.user import User
from app.schemas.tools import (
    ComponentGuideInput,
    ComponentItemInput,
    ComponentVariantInput,
    ExamInput,
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


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


async def _make_user(db, email: str) -> User:
    user = User(
        username=f"u_{_sfx()}",
        email=email,
        hashed_password="$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyh",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user


async def _cleanup_user(db, user_id: int) -> None:
    from sqlalchemy import text

    for table in (
        "user_roles",
        "refresh_tokens",
        "login_history",
        "password_history",
        "notifications",
        "points_transactions",
        "task_claims",
        "exam_attempts",
        "event_registrations",
        "event_checkins",
        "join_applications",
        "two_factor_auth",
        "activity_participations",
        "verification_codes",
        "password_reset_requests",
    ):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE user_id=:i"), {"i": user_id}
                )
        except Exception:
            pass
    for table in ("exams", "tasks", "announcements", "events"):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE created_by=:i"), {"i": user_id}
                )
        except Exception:
            pass
    try:
        async with db.begin_nested():
            await db.execute(
                text("DELETE FROM resources WHERE submitted_by=:i"), {"i": user_id}
            )
    except Exception:
        pass
    await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": user_id})
    await db.commit()


@pytest.mark.integration
async def test_exam_flow(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = ExamService(db)
        u = await _make_user(db, f"ex_{sfx}@t.com")
        try:
            exam = await svc.create_exam(
                u.id,
                ExamInput(title=f"考试-{sfx}", tech_tags=["web", "js"], status="draft"),
            )
            q1 = await svc.create_question(
                exam.id,
                QuestionInput(
                    title="1+1=?",
                    type="single_choice",
                    score=5,
                    options=[
                        {"label": "A", "content": "1", "is_correct": False},
                        {"label": "B", "content": "2", "is_correct": True},
                    ],
                ),
            )
            await svc.publish_exam(exam.id)

            # 答题（正确/错误）
            ok = await svc.submit_answer(u.id, exam.id, q1.id, "B")
            assert ok["is_correct"] is True and ok["score"] == 5
            wrong = await svc.submit_answer(u.id, exam.id, q1.id, "A")
            assert wrong["is_correct"] is False and wrong["score"] == 0

            attempts = await svc.user_attempts(u.id, exam.id)
            assert len(attempts) == 1  # upsert

            ranking = await svc.exam_ranking(exam.id)
            assert len(ranking) == 1
            assert ranking[0]["total_score"] == 0

            await svc.end_exam(exam.id)
            assert (await svc.get_exam(exam.id)).status == "ended"

            await svc.delete_exam(exam.id)
            from app.core.exceptions import NotFoundException

            with pytest.raises(NotFoundException):
                await svc.get_exam(exam.id)
        finally:
            await _cleanup_user(db, u.id)
            await db.execute(delete(Exam).where(Exam.title.like(f"%{sfx}%")))
            await db.commit()


@pytest.mark.integration
async def test_resource_flow(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = ResourceService(db)
        u = await _make_user(db, f"rs_{sfx}@t.com")
        try:
            resource = await svc.create_resource(
                u.id,
                ResourceInput(
                    title=f"资源-{sfx}", url="https://example.com", tech_tags=["web"]
                ),
            )
            assert resource.status == "pending"

            approved = await svc.review_resource(admin_user, resource.id, True, "ok")
            assert approved.status == "approved"

            items, total = await svc.list_resources(status="approved")
            assert any(r.id == resource.id for r in items)

            await svc.increment_view(resource.id)
            assert (await svc.get_resource(resource.id)).view_count == 1

            rejected = await svc.review_resource(admin_user, resource.id, False, "no")
            assert rejected.status == "rejected"
        finally:
            await _cleanup_user(db, u.id)
            await db.execute(delete(Resource).where(Resource.title.like(f"%{sfx}%")))
            await db.commit()


@pytest.mark.integration
async def test_task_and_points_flow(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        task_svc = TaskService(db)
        points_svc = PointsService(db)
        u = await _make_user(db, f"tk_{sfx}@t.com")
        u2 = await _make_user(db, f"tk2_{sfx}@t.com")
        try:
            task = await task_svc.create_task(
                u.id,
                TaskInput(
                    title=f"任务-{sfx}",
                    description="写篇文章",
                    points=20,
                    max_claimants=1,
                ),
            )
            await task_svc.publish_task(task.id)

            claim = await task_svc.claim_task(u.id, task.id, "我来")
            assert claim.status == "claimed"

            # 名额已满
            with pytest.raises(ConflictException):
                await task_svc.claim_task(u2.id, task.id)

            # 重复认领
            with pytest.raises(ConflictException):
                await task_svc.claim_task(u.id, task.id)

            # 提交 + 审核 → 积分
            await task_svc.submit_claim(u.id, claim.id)
            reviewed = await task_svc.review_claim(admin_user, claim.id, True, "通过")
            assert reviewed.status == "approved"

            profile = await points_svc.profile(u.id)
            assert profile["balance"] == 20
            assert profile["level"] == 1

            leaderboard = await points_svc.leaderboard()
            assert any(e["user_id"] == u.id for e in leaderboard)

            # 扣积分
            await points_svc.deduct_points(u.id, 5, "system", None, "测试扣除")
            assert await points_svc.balance(u.id) == 15
        finally:
            from sqlalchemy import text

            for uid in (u.id, u2.id):
                await db.execute(
                    text("DELETE FROM points_transactions WHERE user_id=:i"), {"i": uid}
                )
            await _cleanup_user(db, uid)
            await db.execute(delete(Task).where(Task.title.like(f"%{sfx}%")))
            await db.commit()


@pytest.mark.integration
async def test_auxilio(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = AuxilioService(db)
        exam_svc = ExamService(db)
        resource_svc = ResourceService(db)
        u = await _make_user(db, f"ax_{sfx}@t.com")
        try:
            # 造数据：web 标签考试 + 错题 + 一个 web 资源
            exam = await exam_svc.create_exam(
                u.id,
                ExamInput(title=f"aux-{sfx}", tech_tags=["web"], status="published"),
            )
            q = await exam_svc.create_question(
                exam.id,
                QuestionInput(
                    title="q",
                    type="single_choice",
                    score=5,
                    options=[
                        {"label": "A", "content": "x", "is_correct": True},
                        {"label": "B", "content": "y", "is_correct": False},
                    ],
                ),
            )
            await exam_svc.submit_answer(u.id, exam.id, q.id, "B")  # 错误
            await resource_svc.create_resource(
                u.id,
                ResourceInput(
                    title=f"资源aux-{sfx}", url="https://example.com", tech_tags=["web"]
                ),
            )
            resources, _ = await resource_svc.list_resources()
            for r in resources:
                if r.title.startswith(f"资源aux-{sfx}"):
                    await resource_svc.review_resource(admin_user, r.id, True, "ok")

            analysis = await svc.analyze_learning_profile(u.id)
            assert any(t["tag"] == "web" for t in analysis["weak_tags"])
            assert len(analysis["recommended_resources"]) >= 1
        finally:
            await _cleanup_user(db, u.id)
            await db.execute(delete(Exam).where(Exam.title.like(f"%{sfx}%")))
            await db.execute(delete(Resource).where(Resource.title.like(f"%aux{sfx}%")))
            await db.commit()


@pytest.mark.integration
async def test_component_registry(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = ComponentRegistryService(db)
        try:
            item = await svc.create_component(
                ComponentItemInput(
                    name=f"组件-{sfx}", slug=f"comp-{sfx}", category="button"
                )
            )
            assert item.slug == f"comp-{sfx}"

            # slug 冲突
            with pytest.raises(ConflictException):
                await svc.create_component(
                    ComponentItemInput(name="重复", slug=f"comp-{sfx}")
                )

            # variants
            updated = await svc.replace_variants(
                item.id,
                [
                    ComponentVariantInput(size="md", color="primary", state="default"),
                    ComponentVariantInput(size="lg", color="primary", state="default"),
                ],
            )
            assert len(updated.variants) == 2

            # guide
            with_guide = await svc.update_guide(
                item.id,
                ComponentGuideInput(use_cases=["表单"], anti_patterns=["勿滥用"]),
            )
            assert with_guide.guide is not None
            assert with_guide.guide.use_cases == ["表单"]

            # toggle
            variant_id = updated.variants[0].id
            toggled = await svc.toggle_variant(item.id, variant_id, False)
            assert toggled.variants[0].is_enabled is False

            await svc.delete_component(item.id)
        finally:
            await db.execute(
                delete(ComponentRegistryItem).where(
                    ComponentRegistryItem.slug.like(f"%{sfx}%")
                )
            )
            await db.commit()
