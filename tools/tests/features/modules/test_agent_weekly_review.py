"""AG-P3-04 每周复盘集成测试（需要 PostgreSQL）。

覆盖：周窗口聚合（专注/任务/社区）、同周去重、失败降级。
（新增错题节因错题本 FK 链较重不在本文件验证，采集器与简报同构。）
"""

import uuid

import pytest
from sqlalchemy import delete, text

from app.core.timezone import now_local, now_utc
from app.database import get_session
from app.models.agent_weekly_review import AgentWeeklyReview
from app.models.community import CommunityPost
from app.models.focus import FocusSession
from app.models.task import Task, TaskClaim
from app.models.user import User
from app.services.agent_weekly_review_service import (
    AgentWeeklyReviewService,
    monday_of,
)


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


async def _make_user(db, email: str) -> User:
    user = User(
        username=f"u_{_sfx()}",
        email=email,
        hashed_password="$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyh",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    return user


async def _cleanup(db, *user_ids: int) -> None:
    await db.execute(
        delete(AgentWeeklyReview).where(AgentWeeklyReview.user_id.in_(user_ids))
    )
    await db.execute(delete(FocusSession).where(FocusSession.user_id.in_(user_ids)))
    await db.execute(delete(TaskClaim).where(TaskClaim.user_id.in_(user_ids)))
    await db.execute(delete(Task).where(Task.created_by.in_(user_ids)))
    await db.execute(delete(CommunityPost).where(CommunityPost.author_id.in_(user_ids)))
    for uid in user_ids:
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_weekly_review_generate_dedupe_and_sections(integration_db_ready):
    sfx = _sfx()
    now = now_utc()
    async with get_session() as db:
        svc = AgentWeeklyReviewService(db)
        user = await _make_user(db, f"wk_{sfx}@t.com")
        try:
            task = Task(
                title=f"周任务-{sfx}",
                description="d",
                category="dev",
                status="published",
                created_by=user.id,
            )
            db.add(task)
            await db.flush()
            db.add_all(
                [
                    FocusSession(
                        user_id=user.id,
                        duration_seconds=40 * 60,
                        phase="focus",
                        started_at=now,
                    ),
                    FocusSession(
                        user_id=user.id,
                        duration_seconds=20 * 60,
                        phase="focus",
                        started_at=now,
                    ),
                    TaskClaim(
                        task_id=task.id,
                        user_id=user.id,
                        status="approved",
                        completed_at=now,
                    ),
                    CommunityPost(
                        kind="topic",
                        title=f"周帖-{sfx}",
                        content_markdown="c",
                        status="published",
                        author_id=user.id,
                        created_at=now,
                    ),
                ]
            )
            await db.commit()

            review = await svc.get_or_generate(user.id)
            assert review.status == "ready"
            assert review.week_start == monday_of(now_local().date())
            c = review.content or {}
            assert c.get("focusMinutes") == 60
            assert c.get("communityPosts") == 1
            assert c.get("tasksApproved") == 1
            assert isinstance(c.get("nextWeekHints"), list)

            again = await svc.get_or_generate(user.id)
            assert again.id == review.id
        finally:
            await _cleanup(db, user.id)


@pytest.mark.integration
async def test_weekly_review_failure_degrades(integration_db_ready, monkeypatch):
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentWeeklyReviewService(db)
        user = await _make_user(db, f"wkfail_{sfx}@t.com")
        try:

            async def _boom(*args, **kwargs):
                raise RuntimeError("采集失败")

            monkeypatch.setattr(svc, "_collect_focus", _boom)
            review = await svc.get_or_generate(user.id)
            assert review.status == "failed"
            assert review.content is not None
            assert review.content.get("focusMinutes") is None
        finally:
            await _cleanup(db, user.id)
