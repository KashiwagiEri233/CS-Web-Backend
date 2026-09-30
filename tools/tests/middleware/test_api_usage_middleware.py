"""API 调用埋点中间件测试（纯 ASGI 实现与批量落库）。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.middleware.api_usage as api_usage_module
from app.middleware.api_usage import (
    ApiUsageMiddleware,
    _flush_loop,
    _flush_once,
    shutdown_api_usage_flush,
    startup_api_usage_flush,
)


@pytest.fixture(autouse=True)
def clean_api_usage_state():
    """每次测试前后清空缓冲，并重置当前测试 loop 绑定的 _stop 事件。"""
    api_usage_module._buffer.clear()
    api_usage_module._stop = asyncio.Event()
    if api_usage_module._flush_task and not api_usage_module._flush_task.done():
        api_usage_module._flush_task.cancel()
    api_usage_module._flush_task = None
    yield
    api_usage_module._buffer.clear()
    api_usage_module._stop.set()
    if api_usage_module._flush_task and not api_usage_module._flush_task.done():
        api_usage_module._flush_task.cancel()
    api_usage_module._flush_task = None


async def test_non_http_scope_passthrough():
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    mw = ApiUsageMiddleware(app)
    await mw({"type": "websocket"}, None, None)
    assert called is True
    assert len(api_usage_module._buffer) == 0


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/readyz",
        "/docs",
        "/openapi.json",
        "/workbench/stats/api-usage",
        "/workbench/stats/api-usage/sub",
    ],
)
async def test_silent_prefixes_skipped(path):
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    mw = ApiUsageMiddleware(app)
    await mw({"type": "http", "path": path}, None, None)
    assert called is True
    assert len(api_usage_module._buffer) == 0


async def test_normal_request_buffered_with_status_and_latency():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 201})
        await send({"type": "http.response.body", "body": b""})

    mw = ApiUsageMiddleware(app)
    sent = []

    async def dummy_send(msg):
        sent.append(msg)

    await mw(
        {"type": "http", "path": "/api/v1/posts/123", "method": "POST"},
        None,
        dummy_send,
    )

    assert len(api_usage_module._buffer) == 1
    endpoint, method, status, latency = api_usage_module._buffer[0]
    assert endpoint == "/api/v1/posts/{id}"
    assert method == "POST"
    assert status == 201
    assert isinstance(latency, int)


async def test_request_exception_still_records_buffer():
    async def app(scope, receive, send):
        raise RuntimeError("boom")

    mw = ApiUsageMiddleware(app)
    with pytest.raises(RuntimeError, match="boom"):
        await mw({"type": "http", "path": "/api/v1/fail", "method": "GET"}, None, None)

    assert len(api_usage_module._buffer) == 1
    endpoint, method, status, latency = api_usage_module._buffer[0]
    assert endpoint == "/api/v1/fail"
    assert method == "GET"
    assert status == 200


def test_endpoint_of_edge_cases():
    assert ApiUsageMiddleware._endpoint_of("/") == "/"
    assert ApiUsageMiddleware._endpoint_of("/other/123") == "/other/123"
    assert (
        ApiUsageMiddleware._endpoint_of("/api/v1/tools/exam/99")
        == "/api/v1/tools/exam/{id}"
    )


async def test_flush_once_empty():
    assert await _flush_once() == 0


async def test_flush_once_success(monkeypatch):
    for i in range(5):
        api_usage_module._buffer.append((f"/api/{i}", "GET", 200, 10))

    mock_session = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session.commit = AsyncMock()

    class _ContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _ContextManager())

    count = await _flush_once()
    assert count == 5
    assert len(api_usage_module._buffer) == 0
    mock_session.add_all.assert_called_once()
    logs = mock_session.add_all.call_args[0][0]
    assert len(logs) == 5
    assert logs[0].endpoint == "/api/0"
    mock_session.commit.assert_awaited_once()


async def test_flush_once_batch_size_limit(monkeypatch):
    batch_max = api_usage_module.API_USAGE_FLUSH_BATCH_SIZE
    for i in range(batch_max + 10):
        api_usage_module._buffer.append((f"/api/{i}", "GET", 200, 10))

    mock_session = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session.commit = AsyncMock()

    class _ContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _ContextManager())

    count = await _flush_once()
    assert count == batch_max
    assert len(api_usage_module._buffer) == 10


async def test_flush_once_exception_silently_handled(monkeypatch):
    api_usage_module._buffer.append(("/api/error", "GET", 200, 10))

    mock_session = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session.commit = AsyncMock(side_effect=RuntimeError("db error"))

    class _ContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _ContextManager())

    count = await _flush_once()
    assert count == 0


async def test_flush_loop_execution_and_stop():
    flush_counts = []

    async def mock_flush_once():
        flush_counts.append(1)
        if len(flush_counts) >= 2:
            api_usage_module._stop.set()
        return 1

    with patch.object(api_usage_module, "_flush_once", side_effect=mock_flush_once):
        await _flush_loop(interval=0.01)

    assert len(flush_counts) >= 2


async def test_flush_loop_handles_exception_and_continues():
    call_count = 0

    async def error_flush_once():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("temporary error")
        api_usage_module._stop.set()
        return 0

    with patch.object(api_usage_module, "_flush_once", side_effect=error_flush_once):
        await _flush_loop(interval=0.01)

    assert call_count >= 2


async def test_startup_disabled_when_interval_zero(monkeypatch):
    monkeypatch.setattr(api_usage_module, "API_USAGE_FLUSH_INTERVAL_SECONDS", 0)
    await startup_api_usage_flush()
    assert api_usage_module._flush_task is None


async def test_startup_and_shutdown_full_cycle(monkeypatch):
    monkeypatch.setattr(api_usage_module, "API_USAGE_FLUSH_INTERVAL_SECONDS", 10.0)
    await startup_api_usage_flush()
    assert api_usage_module._flush_task is not None
    assert not api_usage_module._flush_task.done()

    api_usage_module._buffer.append(("/api/shutdown", "GET", 200, 5))
    drained = []

    async def fake_flush_once():
        if api_usage_module._buffer:
            drained.append(api_usage_module._buffer.popleft())
            return 1
        return 0

    monkeypatch.setattr(api_usage_module, "_flush_once", fake_flush_once)

    await shutdown_api_usage_flush()
    assert api_usage_module._stop.is_set()
    assert api_usage_module._flush_task is None
    assert len(drained) == 1
