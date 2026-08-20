"""周期维护任务的锁、清理和生命周期测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import app.database as database_module
import app.repositories.refresh_token_repo as refresh_repo_module
import app.services.data_retention as data_retention
import app.services.exception_retention as retention
import app.services.maintenance_cron as mc
import app.services.token_gc as token_gc


class _FakeSession:
    def __init__(self, lock_acquired: bool) -> None:
        self.lock_acquired = lock_acquired
        self.commit = AsyncMock()

    async def scalar(self, statement, params):
        return self.lock_acquired


def _session_factory(session):
    @asynccontextmanager
    async def _get_session():
        yield session

    return _get_session


async def test_token_gc_skips_when_cluster_lock_is_busy(monkeypatch):
    session = _FakeSession(lock_acquired=False)
    monkeypatch.setattr(database_module, "get_session", _session_factory(session))

    assert await token_gc._purge_once() == 0
    session.commit.assert_not_awaited()


async def test_token_gc_purges_and_commits(monkeypatch):
    session = _FakeSession(lock_acquired=True)
    repo = AsyncMock()
    repo.purge_expired.return_value = 4
    monkeypatch.setattr(database_module, "get_session", _session_factory(session))
    monkeypatch.setattr(refresh_repo_module, "RefreshTokenRepository", lambda db: repo)

    assert await token_gc._purge_once() == 4
    repo.purge_expired.assert_awaited_once_with()
    session.commit.assert_awaited_once_with()


async def test_exception_retention_purges_under_lock(monkeypatch):
    session = _FakeSession(lock_acquired=True)
    service = AsyncMock()
    service.purge_before.return_value = 3
    monkeypatch.setattr(database_module, "get_session", _session_factory(session))
    # 注：_purge_once 使用 retention 模块顶层名 ExceptionService（ER-27 提顶层后），
    # 须 patch retention.ExceptionService 而非 exception_service 模块名。
    monkeypatch.setattr(retention, "ExceptionService", lambda db: service)

    assert await retention._purge_once() == 3
    service.purge_before.assert_awaited_once()


async def test_exception_retention_skips_when_cluster_lock_is_busy(monkeypatch):
    session = _FakeSession(lock_acquired=False)
    monkeypatch.setattr(database_module, "get_session", _session_factory(session))

    assert await retention._purge_once() == 0


async def test_token_gc_startup_runs_once_when_enabled(monkeypatch):
    purged = AsyncMock(return_value=2)
    monkeypatch.setattr(token_gc, "_purge_once", purged)
    monkeypatch.setattr(token_gc.settings, "REFRESH_TOKEN_GC_INTERVAL_SECONDS", 3600)
    await token_gc.startup_refresh_token_gc()
    purged.assert_awaited_once()


async def test_token_gc_startup_skips_when_disabled(monkeypatch):
    purged = AsyncMock(return_value=2)
    monkeypatch.setattr(token_gc, "_purge_once", purged)
    monkeypatch.setattr(token_gc.settings, "REFRESH_TOKEN_GC_INTERVAL_SECONDS", 0)
    await token_gc.startup_refresh_token_gc()
    purged.assert_not_awaited()


async def test_exception_retention_startup_runs_once_when_enabled(monkeypatch):
    purged = AsyncMock(return_value=3)
    monkeypatch.setattr(retention, "_purge_once", purged)
    monkeypatch.setattr(
        retention.settings, "EXCEPTION_LOG_CLEANUP_INTERVAL_SECONDS", 86400
    )
    await retention.startup_exception_log_retention()
    purged.assert_awaited_once()


async def test_exception_retention_startup_skips_when_disabled(monkeypatch):
    purged = AsyncMock(return_value=3)
    monkeypatch.setattr(retention, "_purge_once", purged)
    monkeypatch.setattr(retention.settings, "EXCEPTION_LOG_CLEANUP_INTERVAL_SECONDS", 0)
    await retention.startup_exception_log_retention()
    purged.assert_not_awaited()


async def test_data_retention_startup_runs_when_either_interval_enabled(monkeypatch):
    purged = AsyncMock(return_value={"login_history": 1, "audit_log": 2})
    monkeypatch.setattr(data_retention, "_purge_once", purged)
    monkeypatch.setattr(
        data_retention.settings, "LOGIN_HISTORY_CLEANUP_INTERVAL_SECONDS", 0
    )
    monkeypatch.setattr(
        data_retention.settings, "AUDIT_LOG_CLEANUP_INTERVAL_SECONDS", 0
    )
    await data_retention.startup_data_retention()
    purged.assert_not_awaited()

    monkeypatch.setattr(
        data_retention.settings, "LOGIN_HISTORY_CLEANUP_INTERVAL_SECONDS", 86400
    )
    await data_retention.startup_data_retention()
    purged.assert_awaited_once()


# ===== AR-S2 方案 B：arq cron 包装器与注册 =====


async def test_cron_wrappers_skip_when_disabled(monkeypatch):
    purged = AsyncMock(return_value=5)
    monkeypatch.setattr(mc.token_gc, "_purge_once", purged)
    monkeypatch.setattr(mc.settings, "REFRESH_TOKEN_GC_INTERVAL_SECONDS", 0)
    assert await mc.token_gc_cron(ctx={}) == 0
    purged.assert_not_awaited()


async def test_cron_wrappers_delegate_when_enabled(monkeypatch):
    purged = AsyncMock(return_value=7)
    monkeypatch.setattr(mc.token_gc, "_purge_once", purged)
    monkeypatch.setattr(mc.settings, "REFRESH_TOKEN_GC_INTERVAL_SECONDS", 3600)
    assert await mc.token_gc_cron(ctx={"job_id": "x"}) == 7
    purged.assert_awaited_once()


async def test_data_retention_cron_skips_only_when_both_disabled(monkeypatch):
    purged = AsyncMock(return_value={"login_history": 1, "audit_log": 2})
    monkeypatch.setattr(mc.data_retention, "_purge_once", purged)
    monkeypatch.setattr(mc.settings, "LOGIN_HISTORY_CLEANUP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mc.settings, "AUDIT_LOG_CLEANUP_INTERVAL_SECONDS", 0)
    assert await mc.data_retention_cron(ctx={}) == {"login_history": 0, "audit_log": 0}
    purged.assert_not_awaited()

    monkeypatch.setattr(mc.settings, "LOGIN_HISTORY_CLEANUP_INTERVAL_SECONDS", 86400)
    assert await mc.data_retention_cron(ctx={}) == {"login_history": 1, "audit_log": 2}
    purged.assert_awaited_once()


async def test_cron_jobs_registered():
    import app.core.config as _cfg

    if not _cfg.settings.REDIS_URL:
        _cfg.settings.REDIS_URL = "redis://localhost:6379/0"
    from app.core.queue.worker import WorkerSettings

    names = [c.name for c in WorkerSettings.cron_jobs]
    assert names == [
        "cron:token_gc_cron",
        "cron:data_retention_cron",
        "cron:exception_retention_cron",
    ]
