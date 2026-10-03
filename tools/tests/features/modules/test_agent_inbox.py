"""AG-P3-01 建议收件箱集成测试（需要 PostgreSQL）。

覆盖：
1. create_suggestion：幂等（同 idempotency_key 去重）/ 类型与来源白名单 / confidence 值域；
2. list_inbox：snooze 到期惰性回 pending、pending 过期转 expired；
3. update_status：accept/dismiss 终态、snooze 回写、非 pending 拒绝、
   他人建议 403、不存在 404。
"""

import uuid

import pytest
from sqlalchemy import delete, text

from app.core.exceptions import AuthorizationException, NotFoundException
from app.core.timezone import now_utc
from app.database import get_session
from app.models.agent_inbox import AgentInboxItem
from app.models.user import User
from app.services.agent_inbox_service import AgentInboxService


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


async def _cleanup(db, *user_ids: int) -> None:
    for uid in user_ids:
        await db.execute(delete(AgentInboxItem).where(AgentInboxItem.user_id == uid))
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_create_suggestion_idempotent_and_validated(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentInboxService(db)
        user = await _make_user(db, f"inbox_{sfx}@t.com")
        try:
            item, created = await svc.create_suggestion(
                user.id,
                type="review_due",
                source="scheduler",
                title=f"复习到期-{sfx}",
                idempotency_key=f"review:{sfx}",
                reason="3 个知识点 7 天未复习",
                confidence=0.8,
                estimated_minutes=20,
                payload={"wrongAnswerIds": [1, 2]},
                expires_in_minutes=60,
            )
            assert created is True
            assert item.status == "pending"
            assert item.expires_at is not None

            # 幂等：同键重复产生返回原条目
            again, created2 = await svc.create_suggestion(
                user.id,
                type="review_due",
                source="scheduler",
                title=f"复习到期-{sfx}",
                idempotency_key=f"review:{sfx}",
            )
            assert created2 is False
            assert again.id == item.id

            # 白名单校验
            with pytest.raises(ValueError):
                await svc.create_suggestion(
                    user.id,
                    type="bogus_type",
                    source="scheduler",
                    title="x",
                    idempotency_key=f"bogus:{sfx}",
                )
            with pytest.raises(ValueError):
                await svc.create_suggestion(
                    user.id,
                    type="review_due",
                    source="bogus_source",
                    title="x",
                    idempotency_key=f"bogus2:{sfx}",
                )
            with pytest.raises(ValueError):
                await svc.create_suggestion(
                    user.id,
                    type="review_due",
                    source="exam",
                    title="x",
                    idempotency_key=f"bogus3:{sfx}",
                    confidence=1.5,
                )
        finally:
            await _cleanup(db, user.id)


@pytest.mark.integration
async def test_inbox_lazy_recycle_and_status_machine(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentInboxService(db)
        user = await _make_user(db, f"inbox2_{sfx}@t.com")
        other = await _make_user(db, f"inbox3_{sfx}@t.com")
        try:
            expired, _ = await svc.create_suggestion(
                user.id,
                type="system_hint",
                source="auxilio",
                title=f"已过期-{sfx}",
                idempotency_key=f"exp:{sfx}",
                expires_in_minutes=-1,  # 立即过期
            )
            snoozed, _ = await svc.create_suggestion(
                user.id,
                type="goal_nudge",
                source="scheduler",
                title=f"稍后-{sfx}",
                idempotency_key=f"snooze:{sfx}",
            )
            fresh, _ = await svc.create_suggestion(
                user.id,
                type="resource_recommend",
                source="exam",
                title=f"新鲜-{sfx}",
                idempotency_key=f"fresh:{sfx}",
            )
            # 手工把 snoozed 项置为已到期
            snoozed.status = "snoozed"
            snoozed.snoozed_until = now_utc().replace(year=2020)
            await db.commit()

            items, total = await svc.list_inbox(user)
            by_status = {i.id: i.status for i in items}
            assert by_status[expired.id] == "expired"  # 过期惰性回收
            assert by_status[snoozed.id] == "pending"  # snooze 到期回 pending
            assert by_status[fresh.id] == "pending"
            assert total == 3

            # 处理：accept 终态
            accepted = await svc.update_status(user, fresh.id, "accept")
            assert accepted.status == "accepted"
            assert accepted.resolved_at is not None
            with pytest.raises(ValueError):
                await svc.update_status(user, fresh.id, "dismiss")  # 终态不可再处理

            # 所有权：他人建议 403；不存在 404
            with pytest.raises(AuthorizationException):
                await svc.update_status(other, snoozed.id, "accept")
            with pytest.raises(NotFoundException):
                await svc.update_status(user, 99999999, "accept")

            # snooze：写回 snoozed_until，resolved_at 置空（非终态）
            s = await svc.update_status(user, snoozed.id, "snooze", 30)
            assert s.status == "snoozed"
            assert s.snoozed_until is not None
            assert s.resolved_at is None
        finally:
            await _cleanup(db, user.id, other.id)
