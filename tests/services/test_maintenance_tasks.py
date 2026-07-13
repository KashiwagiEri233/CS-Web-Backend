"""周期维护任务的锁、清理和生命周期测试。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import app.database as database_module
import app.repositories.refresh_token_repo as refresh_repo_module
import app.services.exception_retention as retention
import app.services.exception_service as exception_service_module
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
    monkeypatch.setattr(
        exception_service_module, "ExceptionService", lambda db: service
    )

    assert await retention._purge_once() == 3
    service.purge_before.assert_awaited_once()


async def test_exception_retention_skips_when_cluster_lock_is_busy(monkeypatch):
    session = _FakeSession(lock_acquired=False)
    monkeypatch.setattr(database_module, "get_session", _session_factory(session))

    assert await retention._purge_once() == 0


async def test_maintenance_loops_stop_cleanly(monkeypatch):
    async def stop_token_loop():
        token_gc._stop.set()
        return 1

    async def stop_retention_loop():
        retention._stop.set()
        return 1

    monkeypatch.setattr(token_gc, "_purge_once", stop_token_loop)
    monkeypatch.setattr(retention, "_purge_once", stop_retention_loop)
    token_gc._stop.clear()
    retention._stop.clear()

    await token_gc._gc_loop(1)
    await retention._cleanup_loop(1)


async def test_maintenance_startup_and_shutdown(monkeypatch):
    async def wait_until_stopped(interval):
        await token_gc._stop.wait()

    async def wait_until_retention_stopped(interval):
        await retention._stop.wait()

    monkeypatch.setattr(token_gc.settings, "REFRESH_TOKEN_GC_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(retention.settings, "EXCEPTION_LOG_CLEANUP_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(token_gc, "_gc_loop", wait_until_stopped)
    monkeypatch.setattr(retention, "_cleanup_loop", wait_until_retention_stopped)

    await token_gc.startup_refresh_token_gc()
    await retention.startup_exception_log_retention()
    assert isinstance(token_gc._gc_task, asyncio.Task)
    assert isinstance(retention._cleanup_task, asyncio.Task)

    await token_gc.shutdown_refresh_token_gc()
    await retention.shutdown_exception_log_retention()
    assert token_gc._gc_task is None
    assert retention._cleanup_task is None
