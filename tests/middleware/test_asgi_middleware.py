"""监控 / 日志 / 安全头中间件的行为测试（纯 ASGI 实现）。

这三个中间件从 BaseHTTPMiddleware 改写为原生 ASGI 后，改响应头和统计的时机
从「拿到 Response 对象」变成了「拦截 http.response.start 消息」。本文件锁住
对外可观测的行为，保证这次改写以及后续维护不会悄悄丢头/丢计数。
"""

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

import app.middleware.monitoring as monitoring
from app.middleware.monitoring import (
    LoggingMiddleware,
    MetricsMiddleware,
    SecurityHeadersMiddleware,
)


class _RecordingLogger:
    """记录各级别日志调用，用于断言探针路径确实被静默。"""

    def __init__(self):
        self.calls = []

    def _record(self, level):
        def _log(message, **kwargs):
            self.calls.append((level, message, kwargs))

        return _log

    def __getattr__(self, level):
        return self._record(level)

    def messages(self, level=None):
        return [m for lv, m, _ in self.calls if level is None or lv == level]

    def fields(self, message):
        """取指定日志消息携带的结构化字段。"""
        return next(kw for _lv, m, kw in self.calls if m == message)


def _build_app(*middleware_classes, recorder=None, monkeypatch=None):
    if recorder is not None:
        monkeypatch.setattr(monitoring, "get_logger", lambda name: recorder)

    application = FastAPI()
    for cls in middleware_classes:
        application.add_middleware(cls)

    @application.get("/ok")
    async def ok():
        return {"ok": True}

    @application.get("/health")
    async def health():
        return {"status": "healthy"}

    @application.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    return application


# --------------------------- 安全头 ---------------------------


def test_security_headers_are_added():
    client = TestClient(_build_app(SecurityHeadersMiddleware))
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-xss-protection"] == "1; mode=block"
    assert "max-age=31536000" in resp.headers["strict-transport-security"]


def test_security_headers_do_not_drop_existing_headers():
    """包装 send 时必须保留下游已写入的响应头（如 content-type）。"""
    client = TestClient(_build_app(SecurityHeadersMiddleware))
    resp = client.get("/ok")
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"ok": True}


# --------------------------- 日志 ---------------------------


def test_probe_paths_are_not_logged(monkeypatch):
    recorder = _RecordingLogger()
    client = TestClient(
        _build_app(LoggingMiddleware, recorder=recorder, monkeypatch=monkeypatch)
    )

    client.get("/health")
    assert recorder.calls == []  # 探针完全静默

    client.get("/ok")
    assert "Request completed" in recorder.messages("info")
    # 请求开始降级为 DEBUG，正常运行只留一条 INFO 结果日志
    assert "Request started" in recorder.messages("debug")
    assert "Request started" not in recorder.messages("info")


def test_completed_log_carries_user_id_set_by_downstream(monkeypatch):
    """鉴权依赖写入的 request.state.user_id 必须能被中间件读到。

    纯 ASGI 改写后中间件不再持有 Request 对象，改为从 ``scope["state"]`` 读取——
    这依赖 Starlette 的 ``request.state`` 就是 ``scope["state"]`` 的视图。
    这条断言就是守住这个假设：一旦不成立，日志里的 user_id 会静默变成 None。
    """
    recorder = _RecordingLogger()
    monkeypatch.setattr(monitoring, "get_logger", lambda name: recorder)

    application = FastAPI()
    application.add_middleware(LoggingMiddleware)

    @application.get("/whoami")
    async def whoami(request: Request):
        # 模拟 get_current_user 依赖在鉴权成功后写入用户 id
        request.state.user_id = 4242
        return {"ok": True}

    client = TestClient(application)
    assert client.get("/whoami").status_code == 200
    assert recorder.fields("Request completed")["user_id"] == 4242


def test_process_time_header_present(monkeypatch):
    recorder = _RecordingLogger()
    client = TestClient(
        _build_app(LoggingMiddleware, recorder=recorder, monkeypatch=monkeypatch)
    )
    resp = client.get("/ok")
    assert float(resp.headers["x-process-time"]) >= 0


def test_failed_request_is_logged_and_reraised(monkeypatch):
    recorder = _RecordingLogger()
    client = TestClient(
        _build_app(LoggingMiddleware, recorder=recorder, monkeypatch=monkeypatch),
        raise_server_exceptions=False,
    )
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert "Request failed" in recorder.messages("error")


# --------------------------- 指标 ---------------------------


def test_metrics_counts_requests_and_statuses():
    application = _build_app(MetricsMiddleware)
    client = TestClient(application)
    client.get("/ok")
    client.get("/ok")

    metrics = MetricsMiddleware._instance.get_metrics()
    assert metrics["requests"]["total"] >= 2
    assert metrics["requests"]["by_status"]["200"] >= 2
    assert metrics["requests"]["by_method"]["GET"] >= 2
    assert metrics["requests"]["by_path"]["/ok"] == 2
    assert metrics["performance"]["total_response_time"] > 0


def test_metrics_request_count_header_present():
    client = TestClient(_build_app(MetricsMiddleware))
    resp = client.get("/ok")
    assert int(resp.headers["x-request-count"]) >= 1


def test_metrics_counts_server_errors():
    application = _build_app(MetricsMiddleware)
    client = TestClient(application, raise_server_exceptions=False)

    client.get("/ok")
    instance = MetricsMiddleware._instance
    before = instance.get_metrics()["requests"]["errors"]

    client.get("/boom")
    after = instance.get_metrics()["requests"]["errors"]
    assert after == before + 1


def test_metrics_registers_itself_on_app_state():
    """/metrics/json 端点通过 app.state 取实例（见 main.py）。"""
    application = _build_app(MetricsMiddleware)
    client = TestClient(application)
    client.get("/ok")
    assert application.state.metrics_middleware is MetricsMiddleware._instance


@pytest.mark.parametrize("path", ["/ok", "/health"])
def test_full_stack_preserves_response(path):
    """三个中间件叠在一起时响应体与状态码不受影响。"""
    application = _build_app(
        MetricsMiddleware, LoggingMiddleware, SecurityHeadersMiddleware
    )
    client = TestClient(application)
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
