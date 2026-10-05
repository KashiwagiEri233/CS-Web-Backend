"""AG-P3-06 定时 sweep 集成测试（需要 PostgreSQL）。

覆盖：
1. agent_inbox_sweep：snoozed 到期 → pending、pending 过期 → expired、
   未到期/终态不动；
2. event_auto_archive：过期 upcoming → ended、未来活动不动；
3. AGENT_SWEEPS_ENABLED=False 时 sweep 短路返回 0。
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select, text

from app.core.config import settings
from app.core.timezone import now_utc
from app.database import get_session
from app.models.agent_inbox import AgentInboxItem
from app.models.user import User
from app.schemas.event import EventInput
from app.services.agent_cron import agent_inbox_sweep_cron, event_auto_archive_cron
from app.services.event.event_service import EventService


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
    await db.execute(delete(AgentInboxItem).where(AgentInboxItem.user_id.in_(user_ids)))
    for uid in user_ids:
        await db.execute(text("DELETE FROM events WHERE created_by=:i"), {"i": uid})
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_agent_inbox_sweep_transitions(integration_db_ready, monkeypatch):
    sfx = _sfx()
    async with get_session() as db:
        user = await _make_user(db, f"sweep_{sfx}@t.com")
        now = now_utc()
        rows = {
            "due_snooze": AgentInboxItem(
                user_id=user.id,
                idempotency_key=f"due:{sfx}",
                type="review_due",
                source="scheduler",
                title="到期稍后",
                status="snoozed",
                snoozed_until=now - timedelta(minutes=5),
            ),
            "future_snooze": AgentInboxItem(
                user_id=user.id,
                idempotency_key=f"future:{sfx}",
                type="review_due",
                source="scheduler",
                title="未到期稍后",
                status="snoozed",
                snoozed_until=now + timedelta(hours=1),
            ),
            "stale_pending": AgentInboxItem(
                user_id=user.id,
                idempotency_key=f"stale:{sfx}",
                type="system_hint",
                source="auxilio",
                title="已过期待处理",
                status="pending",
                expires_at=now - timedelta(minutes=1),
            ),
            "fresh_pending": AgentInboxItem(
                user_id=user.id,
                idempotency_key=f"fresh:{sfx}",
                type="system_hint",
                source="auxilio",
                title="新鲜待处理",
                status="pending",
            ),
            "terminal": AgentInboxItem(
                user_id=user.id,
                idempotency_key=f"terminal:{sfx}",
                type="goal_nudge",
                source="exam",
                title="已接受",
                status="accepted",
                resolved_at=now,
            ),
        }
        db.add_all(rows.values())
        await db.commit()
        try:
            result = await agent_inbox_sweep_cron({})
            assert result["promoted"] >= 1
            assert result["expired"] >= 1

            # sweep 在独立 session 执行 UPDATE；本会话 identity map 缓存旧行，
            # 用新会话取终态
            async with get_session() as vq:
                fresh = (
                    (
                        await vq.execute(
                            select(AgentInboxItem).where(
                                AgentInboxItem.user_id == user.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            by_title = {r.title: r.status for r in fresh}
            assert by_title["到期稍后"] == "pending"
            assert by_title["未到期稍后"] == "snoozed"
            assert by_title["已过期待处理"] == "expired"
            assert by_title["新鲜待处理"] == "pending"
            assert by_title["已接受"] == "accepted"
        finally:
            await _cleanup(db, user.id)


@pytest.mark.integration
async def test_agent_inbox_sweep_disabled(integration_db_ready, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_SWEEPS_ENABLED", False)
    assert await agent_inbox_sweep_cron({}) == {"promoted": 0, "expired": 0}


@pytest.mark.integration
async def test_event_auto_archive_cron(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = EventService(db)
        past = await svc.create_event(
            admin_user,
            EventInput(title=f"归档-过期-{sfx}", capacity=5),
        )
        future = await svc.create_event(
            admin_user,
            EventInput(title=f"归档-未来-{sfx}", capacity=5),
        )
        # Event.date 为展示用文本列（String(20)），auto_archive 按字符串日期比较
        past.date = (now_utc() - timedelta(days=1)).date().isoformat()
        await db.commit()
        try:
            count = await event_auto_archive_cron({})
            assert count >= 1

            await db.refresh(past)
            await db.refresh(future)
            assert past.status == "ended"
            assert future.status != "ended"
        finally:
            # 新会话清理：测试体失败时原会话可能处于中止事务态
            async with get_session() as fx:
                await fx.execute(
                    text("DELETE FROM events WHERE created_by=:i"),
                    {"i": admin_user},
                )
                await fx.commit()
