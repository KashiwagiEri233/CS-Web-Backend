"""AG-P3-02 自动化规则集成测试（需要 PostgreSQL）。

覆盖：
1. CRUD：创建（默认停用）/ 更新 / 启停 / 删除 / 所有权 403；
2. 校验：触发类型白名单、静音时段格式、max_per_hour 值域；
3. 裁决器（CR-032 三参数）：静音时段（含跨午夜）、冷却、每小时频次水位
   （依据收件箱建议幂等键前缀 `rule:{id}:` 统计）。
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, text

from app.core.exceptions import AuthorizationException, NotFoundException
from app.core.timezone import now_utc
from app.database import get_session
from app.models.agent_automation import AgentAutomationRule
from app.models.agent_inbox import AgentInboxItem
from app.models.user import User
from app.services.agent_automation_service import (
    AgentAutomationService,
    in_cooldown,
    quiet_hours_active,
)
from datetime import datetime, time


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
    await db.execute(
        delete(AgentAutomationRule).where(AgentAutomationRule.user_id.in_(user_ids))
    )
    for uid in user_ids:
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_rule_crud_and_validation(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentAutomationService(db)
        user = await _make_user(db, f"rule_{sfx}@t.com")
        other = await _make_user(db, f"rule2_{sfx}@t.com")
        try:
            rule = await svc.create_rule(
                user,
                {
                    "name": f"复习提醒-{sfx}",
                    "trigger_type": "review_due",
                    "condition": {"minWrongCount": 3},
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "07:00",
                    "cooldown_minutes": 120,
                    "max_per_hour": 2,
                },
            )
            assert rule.enabled is False  # 默认停用
            assert rule.cooldown_minutes == 120

            # 白名单校验
            with pytest.raises(ValueError):
                await svc.create_rule(
                    user,
                    {
                        "name": "x",
                        "trigger_type": "bogus",
                        "action_type": "inbox_suggestion",
                    },
                )
            with pytest.raises(ValueError):
                await svc.create_rule(
                    user,
                    {
                        "name": "x",
                        "trigger_type": "review_due",
                        "action_type": "send_email",
                    },
                )
            # 静音时段格式
            with pytest.raises(ValueError):
                await svc.create_rule(
                    user,
                    {
                        "name": "x",
                        "trigger_type": "review_due",
                        "action_type": "inbox_suggestion",
                        "quiet_hours_start": "25:00",
                        "quiet_hours_end": "07:00",
                    },
                )

            # 更新 + 启停
            updated = await svc.update_rule(
                user, rule.id, {"name": f"改名-{sfx}", "max_per_hour": 5}
            )
            assert updated.name == f"改名-{sfx}"
            assert updated.max_per_hour == 5
            enabled = await svc.set_enabled(user, rule.id, True)
            assert enabled.enabled is True

            # 所有权
            with pytest.raises(AuthorizationException):
                await svc.set_enabled(other, rule.id, False)
            with pytest.raises(NotFoundException):
                await svc.set_enabled(user, 99999999, True)

            items, total = await svc.list_rules(user, enabled=True)
            assert total == 1 and items[0].id == rule.id

            await svc.delete_rule(user, rule.id)
            items2, _ = await svc.list_rules(user)
            assert all(r.id != rule.id for r in items2)
        finally:
            await _cleanup(db, user.id, other.id)


def test_quiet_hours_and_cooldown_pure_logic():
    """纯函数：静音时段（含跨午夜）与冷却判定。"""
    assert quiet_hours_active("22:00", "07:00", time(23, 30)) is True
    assert quiet_hours_active("22:00", "07:00", time(6, 59)) is True
    assert quiet_hours_active("22:00", "07:00", time(7, 0)) is False
    assert quiet_hours_active("12:00", "14:00", time(13, 0)) is True
    assert quiet_hours_active("12:00", "14:00", time(14, 0)) is False
    assert quiet_hours_active(None, None, time(13, 0)) is False
    assert quiet_hours_active("bad", "07:00", time(13, 0)) is False

    now = datetime(2026, 10, 5, 12, 0)
    assert in_cooldown(now - timedelta(minutes=30), 60, now) is True
    assert in_cooldown(now - timedelta(minutes=61), 60, now) is False
    assert in_cooldown(None, 60, now) is False
    assert in_cooldown(now - timedelta(minutes=30), 0, now) is False


@pytest.mark.integration
async def test_arbitrator_three_parameters(integration_db_ready):
    """裁决器：启停 → 静音时段 → 冷却 → 每小时频次水位。"""
    sfx = _sfx()
    async with get_session() as db:
        svc = AgentAutomationService(db)
        user = await _make_user(db, f"arb_{sfx}@t.com")
        try:
            rule = await svc.create_rule(
                user,
                {
                    "name": f"裁决-{sfx}",
                    "trigger_type": "review_due",
                    "cooldown_minutes": 60,
                    "max_per_hour": 2,
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "07:00",
                },
            )
            # 1) 停用：一律压制
            ok, reason = await svc.arbitrate(rule)
            assert (ok, reason) == (False, "rule_disabled")
            await svc.set_enabled(user, rule.id, True)

            # 2) 静音时段（以规则配置注入 now 的本地时区时间判定）
            from datetime import datetime

            ok, reason = await svc.arbitrate(rule, now=datetime(2026, 10, 5, 23, 30))
            assert (ok, reason) == (False, "quiet_hours")

            # 3) 频次水位：预置 2 条本小时内的放行痕迹（幂等键前缀统计）
            now = now_utc()
            db.add_all(
                [
                    AgentInboxItem(
                        user_id=user.id,
                        idempotency_key=f"rule:{rule.id}:1",
                        type="review_due",
                        source="scheduler",
                        title="痕迹1",
                        created_at=now - timedelta(minutes=10),
                    ),
                    AgentInboxItem(
                        user_id=user.id,
                        idempotency_key=f"rule:{rule.id}:2",
                        type="review_due",
                        source="scheduler",
                        title="痕迹2",
                        created_at=now - timedelta(minutes=5),
                    ),
                ]
            )
            await db.commit()
            ok, reason = await svc.arbitrate(rule)
            assert (ok, reason) == (False, "hourly_cap")

            # 4) 冷却：清掉痕迹（新会话删除），放行一次后写 last_fired_at
            async with get_session() as fx:
                await fx.execute(
                    delete(AgentInboxItem).where(
                        AgentInboxItem.idempotency_key.like(f"rule:{rule.id}:%")
                    )
                )
                await fx.commit()
            ok, reason = await svc.arbitrate(rule)
            assert (ok, reason) == (True, "allowed")
            await svc.mark_fired(rule.id)
            ok, reason = await svc.arbitrate(rule)
            assert (ok, reason) == (False, "cooldown")
        finally:
            await _cleanup(db, user.id)
