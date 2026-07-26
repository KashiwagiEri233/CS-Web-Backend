"""REQUIRE_REDIS_FOR_SECURITY 下 redis_probe 的 fail-closed 行为。"""

import pytest

import app.core.redis_client as redis_module
from app.core.redis_client import startup_redis_probe


async def test_redis_probe_allows_missing_url_when_not_required(monkeypatch):
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", None)
    monkeypatch.setattr(redis_module.settings, "REQUIRE_REDIS_FOR_SECURITY", False)
    await startup_redis_probe()  # 不应抛错


async def test_redis_probe_rejects_missing_url_when_required(monkeypatch):
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", None)
    monkeypatch.setattr(redis_module.settings, "REQUIRE_REDIS_FOR_SECURITY", True)
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        await startup_redis_probe()


async def test_redis_probe_rejects_unreachable_redis_when_required(monkeypatch):
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(redis_module.settings, "REQUIRE_REDIS_FOR_SECURITY", True)

    async def _fail_ping():
        return False

    monkeypatch.setattr(redis_module, "ping_redis", _fail_ping)
    with pytest.raises(RuntimeError, match="Redis 不可用"):
        await startup_redis_probe()


async def test_redis_probe_warns_but_continues_when_optional(monkeypatch):
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(redis_module.settings, "REQUIRE_REDIS_FOR_SECURITY", False)

    async def _fail_ping():
        return False

    monkeypatch.setattr(redis_module, "ping_redis", _fail_ping)
    await startup_redis_probe()  # 非强制时仅降级


async def test_redis_probe_ok_when_required_and_healthy(monkeypatch):
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(redis_module.settings, "REQUIRE_REDIS_FOR_SECURITY", True)

    async def _ok_ping():
        return True

    monkeypatch.setattr(redis_module, "ping_redis", _ok_ping)
    await startup_redis_probe()
