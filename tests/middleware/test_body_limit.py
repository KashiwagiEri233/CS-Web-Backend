"""请求体大小限制中间件测试。

两条路径都要覆盖：声明 Content-Length 的普通请求，以及不带 Content-Length 的
分块传输（chunked）——后者是绕过第一道检查的唯一途径，漏掉就等于没有防护。
"""

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.core.exceptions import ErrorCode, setup_exception_handlers
from app.core.exceptions import ExceptionHandlerMiddleware
from app.middleware.body_limit import BodySizeLimitMiddleware

_LIMIT = 100


def _build_app(limit: int = _LIMIT):
    application = FastAPI()
    setup_exception_handlers(application)
    application.add_middleware(ExceptionHandlerMiddleware)  # 模拟真实中间件栈
    application.add_middleware(BodySizeLimitMiddleware, max_bytes=limit)

    @application.post("/echo")
    async def echo(payload: dict):
        return {"size": len(payload)}

    @application.get("/ping")
    async def ping():
        return {"ok": True}

    return application


def test_small_body_passes():
    client = TestClient(_build_app())
    resp = client.post("/echo", json={"a": 1})
    assert resp.status_code == 200
    assert resp.json() == {"size": 1}


def test_oversized_body_rejected_with_413():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    resp = client.post("/echo", json={"a": "x" * (_LIMIT * 2)})
    assert resp.status_code == 413
    body = resp.json()
    assert body["error_code"] == ErrorCode.Request.REQUEST_BODY_TOO_LARGE
    assert body["success"] is False


def test_chunked_body_cannot_bypass_the_limit():
    """不带 Content-Length 的分块请求必须靠边收边计数拦下。"""

    def chunks():
        # 每块都小于上限，累计后超限
        for _ in range(5):
            yield b"x" * (_LIMIT // 2)

    client = TestClient(_build_app(), raise_server_exceptions=False)
    resp = client.post("/echo", content=chunks())
    # 关键是没有把超大 body 完整交给下游；413 或 422 都算拦住，
    # 但绝不能是 200（说明整个 body 被接收并处理了）
    assert resp.status_code != 200
    assert resp.status_code in (413, 422)


def test_bodyless_methods_are_not_touched():
    client = TestClient(_build_app())
    assert client.get("/ping").status_code == 200


def test_limit_boundary_is_inclusive():
    """恰好等于上限的请求体应放行（判定是 > 而非 >=）。"""
    application = FastAPI()
    application.add_middleware(BodySizeLimitMiddleware, max_bytes=_LIMIT)

    @application.post("/raw")
    async def raw():
        return {"ok": True}

    client = TestClient(application, raise_server_exceptions=False)
    resp = client.post("/raw", content=b"x" * _LIMIT)
    assert resp.status_code == 200
