"""REQUIRE_REDIS_FOR_SECURITY 下 redis_probe 的 fail-closed 行为。"""

import pytest

import app.core.redis_client as redis_module
from app.core.redis_client import startup_redis_probe


async def test_redis_probe_allows_missing_url_when_not_required(monkeypatch):
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", None)
    monkeypatch.setattr(redis_module.settings, "REQUIRE_REDIS_FOR_SECURITY", False)
    await startup_redis_probe()  # 不应抛错


def test_missing_url_rejected_at_config_layer(monkeypatch):
    """缺 REDIS_URL 的防护在**配置校验层**，而非启动探测层。

    比放在 probe 里更早也更可靠：配置非法就拒绝构造 Settings，
    根本走不到启动任务。这里断言防护所在的真实位置，避免测试与实现脱节。
    """
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REQUIRE_REDIS_FOR_SECURITY", "True")
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(_env_file=None)


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
