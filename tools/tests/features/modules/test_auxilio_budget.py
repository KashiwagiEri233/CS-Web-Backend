"""Auxilio 每日 token 预算拦截（W-2 验证）。

覆盖 run_chat 在 LLM_DAILY_BUDGET 用尽时于调用模型前停止：
- 超预算：产出停止文案 + done，且从不调用 llm_client.stream_chat；
- 预算关闭（0 = 不限制）：放行至模型调用。
"""

import uuid

import pytest

from app.core.config import settings
from app.database import get_session
from app.models.user import User
from app.repositories.auxilio_tool_repo import AuxilioToolRepository
from app.services import llm_client
from app.services.auxilio_agent import run_chat


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


async def _make_user(db) -> User:
    user = User(
        username=f"u_{_sfx()}",
        email=f"budget_{_sfx()}@test.local",
        hashed_password="$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyh",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_budget_exhausted_stops_before_model_call(
    integration_db_ready, monkeypatch
):
    """今日用量达预算：产出停止文案并终止，绝不发起模型调用。"""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "LLM_DAILY_BUDGET", 1)

    async def _over_budget(self, user_id):
        return 2 * 1000_000  # 2M tokens >= 1K * 1000 预算上限

    monkeypatch.setattr(AuxilioToolRepository, "llm_usage_today_tokens", _over_budget)

    async def _must_not_call(*args, **kwargs):
        raise AssertionError("超预算后仍尝试调用模型")

    monkeypatch.setattr(llm_client, "stream_chat", _must_not_call)

    async with get_session() as db:
        user = await _make_user(db)
        events = [
            ev async for ev in run_chat(db, user, [{"role": "user", "content": "你好"}])
        ]

    stop = [
        ev
        for ev in events
        if ev["type"] == "delta" and "今日模型用量上限" in ev.get("text", "")
    ]
    assert stop, f"未产出预算停止文案，实际事件: {events}"
    assert events[-1]["type"] == "done"
    assert not any(ev["type"] == "error" for ev in events)


@pytest.mark.asyncio
async def test_budget_zero_disables_gate(integration_db_ready, monkeypatch):
    """LLM_DAILY_BUDGET=0 表示不限制：放行至模型调用。"""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "LLM_DAILY_BUDGET", 0)

    async def _over_budget(self, user_id):
        return 999_999_999

    monkeypatch.setattr(AuxilioToolRepository, "llm_usage_today_tokens", _over_budget)

    called = {"stream": False}

    def _canned_stream(*args, **kwargs):
        called["stream"] = True

        async def _gen():
            yield {"type": "delta", "text": "预算内放行"}
            yield {"type": "done"}

        return _gen()

    monkeypatch.setattr(llm_client, "stream_chat", _canned_stream)

    async with get_session() as db:
        user = await _make_user(db)
        events = [
            ev async for ev in run_chat(db, user, [{"role": "user", "content": "你好"}])
        ]

    assert called["stream"], "预算关闭（0）仍拦截了模型调用"
    assert any(
        ev["type"] == "delta" and "预算内放行" in ev.get("text", "") for ev in events
    )
