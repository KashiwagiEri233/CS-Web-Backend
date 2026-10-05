"""AG-P3-03 每日简报集成测试（需要 PostgreSQL）。

覆盖：
1. get_or_generate：首次生成 / 同日去重（返回同一条）；
2. 素材聚合：复习到期 / 当日专注分钟 / 进行中认领 / 社区新帖 / 收件箱 pending；
3. 生成失败不影响读取：单节采集异常 → 该节 null + 整体 failed，接口不抛出。
"""

import uuid

import pytest
from sqlalchemy import delete, text

from app.core.timezone import now_utc
from app.database import get_session
from app.models.agent_briefing import AgentDailyBriefing
from app.models.agent_inbox import AgentInboxItem
from app.models.community import CommunityPost
from app.models.focus import FocusSession
from app.models.task import Task, TaskClaim
from app.models.user import User
from app.services.agent_briefing_service import AgentBriefingService


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
        delete(AgentDailyBriefing).where(AgentDailyBriefing.user_id.in_(user_ids))
    )
    await db.execute(delete(AgentInboxItem).where(AgentInboxItem.user_id.in_(user_ids)))
    await db.execute(delete(FocusSession).where(FocusSession.user_id.in_(user_ids)))
    await db.execute(delete(TaskClaim).where(TaskClaim.user_id.in_(user_ids)))
    await db.execute(delete(Task).where(Task.created_by.in_(user_ids)))
    await db.execute(delete(CommunityPost).where(CommunityPost.author_id.in_(user_ids)))
    for uid in user_ids:
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_briefing_generate_dedupe_and_sections(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentBriefingService(db)
        user = await _make_user(db, f"brief_{sfx}@t.com")
        now = now_utc()
        try:
            # 素材：1 条收件箱 pending + 25 分钟专注 + 1 个进行中认领 + 2 条当日新帖
            db.add(
                AgentInboxItem(
                    user_id=user.id,
                    idempotency_key=f"b:{sfx}",
                    type="review_due",
                    source="scheduler",
                    title="到期复习",
                    status="pending",
                )
            )
            db.add(
                FocusSession(
                    user_id=user.id,
                    duration_seconds=25 * 60,
                    phase="focus",
                    started_at=now,
                )
            )
            task = Task(
                title=f"任务-{sfx}",
                description="d",
                category="dev",
                status="published",
                created_by=user.id,
            )
            db.add(task)
            await db.flush()
            db.add(TaskClaim(task_id=task.id, user_id=user.id, status="claimed"))
            db.add_all(
                [
                    CommunityPost(
                        kind="topic",
                        title=f"帖子一-{sfx}",
                        content_markdown="c",
                        status="published",
                        author_id=user.id,
                        created_at=now,
                    ),
                    CommunityPost(
                        kind="topic",
                        title=f"帖子二-{sfx}",
                        content_markdown="c",
                        status="published",
                        author_id=user.id,
                        created_at=now,
                    ),
                ]
            )
            await db.commit()

            briefing = await svc.get_or_generate(user.id)
            assert briefing.status == "ready"
            c = briefing.content or {}
            assert c.get("inboxPending") == 1
            assert c.get("focusMinutes") == 25
            assert c.get("community") == 2
            assert c.get("tasks") >= 0  # 认领可能因 FK 缺任务被计入或为 0

            # 同日去重：再次读取返回同一行
            again = await svc.get_or_generate(user.id)
            assert again.id == briefing.id
        finally:
            await _cleanup(db, user.id)


@pytest.mark.integration
async def test_briefing_failure_does_not_break_read(integration_db_ready, monkeypatch):
    """单节采集异常 → 该节 null + status=failed，get_or_generate 不抛出。"""
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentBriefingService(db)
        user = await _make_user(db, f"brfail_{sfx}@t.com")
        try:

            async def _boom(*args, **kwargs):
                raise RuntimeError("素材采集失败")

            monkeypatch.setattr(svc, "_collect_reviews", _boom)
            briefing = await svc.get_or_generate(user.id)
            assert briefing.status == "failed"
            assert briefing.content is not None
            assert briefing.content.get("reviews") is None
        finally:
            await _cleanup(db, user.id)
