"""ExceptionHandlerMiddleware 异常映射测试。

验证：功能中间件层抛出的异常被最外层 ExceptionHandlerMiddleware 按类型映射为
正确的 HTTP 状态码，而不是一律吞成 500。不依赖数据库。
"""

from fastapi import FastAPI, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient

from app.core.exceptions import (
    setup_exception_handlers,
    ExceptionHandlerMiddleware,
    NotFoundException,
)


class _RaiseMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path == "/http403":
            raise HTTPException(status_code=403, detail="forbidden")
        if path == "/biz":
            raise NotFoundException(resource_type="thing", resource_id="x")
        if path == "/boom":
            raise RuntimeError("kaboom")
        return await call_next(request)


def _client():
    app = FastAPI()
    setup_exception_handlers(app)
    # 顺序：_RaiseMiddleware 内层(先加)，ExceptionHandler 外层(后加)
    app.add_middleware(_RaiseMiddleware)
    app.add_middleware(ExceptionHandlerMiddleware)

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_http_exception_in_middleware_keeps_status():
    resp = _client().get("/http403")
    assert resp.status_code == 403
    assert resp.json()["statusCode"] == 403


def test_app_exception_in_middleware_maps_to_its_status():
    resp = _client().get("/biz")
    assert resp.status_code == 404
    assert resp.json()["errorCode"] == "RESOURCE_NOT_FOUND"


def test_unknown_exception_in_middleware_is_500():
    resp = _client().get("/boom")
    assert resp.status_code == 500
    assert resp.json()["errorCode"] == "INTERNAL_SERVER_ERROR"


def test_normal_request_passes_through():
    resp = _client().get("/ok")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_request_id_is_returned_and_valid_incoming_value_is_preserved():
    resp = _client().get("/ok", headers={"X-Request-ID": "client-request-123"})
    assert resp.headers["x-request-id"] == "client-request-123"


def test_invalid_request_id_is_replaced():
    resp = _client().get("/ok", headers={"X-Request-ID": "bad id"})
    assert resp.headers["x-request-id"] != "bad id"
    assert len(resp.headers["x-request-id"]) == 32
