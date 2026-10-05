"""AG-P3-05 事件触发引擎集成测试（需要 PostgreSQL）。

覆盖（resource_new 触发器，无复杂 FK 依赖）：
1. 启用规则 + 新审核资源 → 裁决放行 → 建议入库（幂等键 rule:{id}:{date}，
   类型映射 resource_recommend）→ mark_fired；
2. 同日重扫：幂等键 + 冷却双重防线 → 不重复生成；
3. 停用规则 → 裁决压制；无信号 → no_signal；开关关闭 → cron 短路。
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, text

from app.core.timezone import now_utc
from app.database import get_session
from app.models.agent_automation import AgentAutomationRule
from app.models.agent_inbox import AgentInboxItem
from app.models.resource import Resource
from app.models.user import User
from app.services.agent_automation_service import AgentAutomationService
from app.services.agent_cron import agent_trigger_cron
from app.services.agent_trigger_service import AgentTriggerService


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
    await db.execute(delete(Resource).where(Resource.submitted_by.in_(user_ids)))
    await db.execute(
        delete(AgentAutomationRule).where(AgentAutomationRule.user_id.in_(user_ids))
    )
    for uid in user_ids:
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_resource_trigger_creates_and_dedupes(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentTriggerService(db)
        auto = AgentAutomationService(db)
        user = await _make_user(db, f"trig_{sfx}@t.com")
        submitter = await _make_user(db, f"trigsub_{sfx}@t.com")
        try:
            rule = await auto.create_rule(
                user,
                {
                    "name": f"新资源-{sfx}",
                    "trigger_type": "resource_new",
                    "cooldown_minutes": 60,
                    "max_per_hour": 3,
                },
            )
            await auto.set_enabled(user, rule.id, True)

            db.add(
                Resource(
                    title=f"新资源-{sfx}",
                    url=f"https://t.com/{sfx}",
                    resource_type="article",
                    status="approved",
                    submitted_by=submitter.id,
                    created_at=now_utc() - timedelta(minutes=10),
                )
            )
            await db.commit()

            summary = await svc.scan_enabled_rules()
            assert summary["scanned"] >= 1
            assert summary["created"] >= 1

            items = (
                (
                    await db.execute(
                        select(AgentInboxItem).where(
                            AgentInboxItem.idempotency_key.like(f"rule:{rule.id}:%")
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(items) == 1
            assert items[0].idempotency_key == f"rule:{rule.id}:{now_utc():%Y%m%d}"
            assert items[0].type == "resource_recommend"
            assert items[0].payload is not None
            assert items[0].payload.get("ruleId") == rule.id

            # 同日重扫：幂等键 + 冷却双重防线
            summary2 = await svc.scan_enabled_rules()
            fresh = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(AgentInboxItem)
                        .where(AgentInboxItem.idempotency_key.like(f"rule:{rule.id}:%"))
                    )
                ).scalar_one()
            )
            assert fresh == 1
            assert summary2["created"] == 0
        finally:
            await _cleanup(db, user.id, submitter.id)


@pytest.mark.integration
async def test_trigger_skips_disabled_and_no_signal(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentTriggerService(db)
        auto = AgentAutomationService(db)
        user = await _make_user(db, f"trig2_{sfx}@t.com")
        try:
            rule = await auto.create_rule(
                user, {"name": f"停用-{sfx}", "trigger_type": "resource_new"}
            )
            ok, reason = await auto.arbitrate(rule)
            assert (ok, reason) == (False, "rule_disabled")

            await auto.set_enabled(user, rule.id, True)
            summary = await svc.scan_enabled_rules()
            assert summary["scanned"] >= 1
            items = (
                (
                    await db.execute(
                        select(AgentInboxItem).where(AgentInboxItem.user_id == user.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(items) == 0  # 无 24h 内新资源 → no_signal
        finally:
            await _cleanup(db, user.id)


@pytest.mark.integration
async def test_goal_stalled_trigger(integration_db_ready):
    """goal_stalled：active 目标 + 从未专注 → goal_nudge 建议。"""
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentTriggerService(db)
        auto = AgentAutomationService(db)
        user = await _make_user(db, f"trig3_{sfx}@t.com")
        try:
            from app.models.learning_goal import LearningGoal

            rule = await auto.create_rule(
                user,
                {
                    "name": f"停滞-{sfx}",
                    "trigger_type": "goal_stalled",
                    "condition": {"days": 7},
                },
            )
            await auto.set_enabled(user, rule.id, True)
            db.add(LearningGoal(user_id=user.id, title=f"目标-{sfx}", status="active"))
            await db.commit()

            ok, reason = await svc.evaluate_rule(rule)
            assert ok is True
            item = (
                (
                    await db.execute(
                        select(AgentInboxItem).where(
                            AgentInboxItem.idempotency_key
                            == f"rule:{rule.id}:{now_utc():%Y%m%d}"
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert item.type == "goal_nudge"
        finally:
            await _cleanup(db, user.id)


@pytest.mark.integration
async def test_trigger_cron_wrapper_enabled(integration_db_ready):
    """开关开启：cron 包装层真实执行扫描并返回摘要（规则在扫描期间存在）。"""
    sfx = _sfx()
    async with get_session() as db:
        auto = AgentAutomationService(db)
        user = await _make_user(db, f"trig4_{sfx}@t.com")
        rule = await auto.create_rule(
            user, {"name": f"扫描-{sfx}", "trigger_type": "resource_new"}
        )
        await auto.set_enabled(user, rule.id, True)

    from app.core.config import settings

    assert settings.AGENT_SWEEPS_ENABLED is True
    summary = await agent_trigger_cron({})
    assert summary["scanned"] >= 1
    assert summary["failed"] == 0

    async with get_session() as db:
        await _cleanup(db, user.id)


@pytest.mark.integration
async def test_trigger_cron_wrapper_disabled(integration_db_ready, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_SWEEPS_ENABLED", False)
    assert await agent_trigger_cron({}) == {
        "scanned": 0,
        "created": 0,
        "gated": 0,
        "no_signal": 0,
        "failed": 0,
    }
