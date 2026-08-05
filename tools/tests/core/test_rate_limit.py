"""可降级限流子系统测试。

覆盖：
- InMemoryBackend 滑动窗口
- RedisBackend 的调用约定（用 fake client 模拟 Lua 脚本）
- DegradableRateLimiter 的降级 / 半开恢复 / 放行策略
- 中间件端到端返回 429（含被 ExceptionHandlerMiddleware 正确放行而非吞成 500）

全部不依赖真实 Redis / 数据库，可离线运行。
"""

import time
from ipaddress import ip_network

from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from app.core.rate_limit.backends import InMemoryBackend, RedisBackend
from app.core.rate_limit.limiter import DegradableRateLimiter
from app.core.request_context import get_client_ip
from app.middleware.rate_limit import (
    AuthRateLimitMiddleware,
    RateLimitMiddleware,
)
from app.core.exceptions import setup_exception_handlers, ExceptionHandlerMiddleware

# ----------------------------- 后端 -----------------------------


async def test_inmemory_blocks_after_limit():
    backend = InMemoryBackend()
    results = [await backend.is_allowed("ip", 3, 60) for _ in range(5)]
    assert results == [True, True, True, False, False]


async def test_inmemory_keys_are_isolated():
    backend = InMemoryBackend()
    assert await backend.is_allowed("a", 1, 60) is True
    assert await backend.is_allowed("a", 1, 60) is False
    # 不同 key 互不影响
    assert await backend.is_allowed("b", 1, 60) is True


async def test_inmemory_window_expiry(monkeypatch):
    backend = InMemoryBackend()
    t = {"now": 1000.0}
    # 内存限流用单调时钟（防系统时钟回拨），测试同步 patch monotonic
    monkeypatch.setattr(time, "monotonic", lambda: t["now"])
    assert await backend.is_allowed("ip", 2, 10) is True
    assert await backend.is_allowed("ip", 2, 10) is True
    assert await backend.is_allowed("ip", 2, 10) is False  # 满
    t["now"] += 11  # 窗口滑过
    assert await backend.is_allowed("ip", 2, 10) is True  # 旧记录已过期


class _FakeScript:
    """模拟 register_script 返回的 AsyncScript：在进程内复刻滑动窗口逻辑。"""

    def __init__(self):
        self._store = {}

    async def __call__(self, keys, args):
        key = keys[0]
        now, window, limit, member = (
            float(args[0]),
            float(args[1]),
            int(args[2]),
            args[3],
        )
        bucket = [m for m in self._store.get(key, []) if m[0] > now - window]
        if len(bucket) >= limit:
            self._store[key] = bucket
            return 0
        bucket.append((now, member))
        self._store[key] = bucket
        return 1


class _FakeRedis:
    def __init__(self):
        self._script = _FakeScript()

    def register_script(self, _src):
        return self._script


async def test_redis_backend_allows_then_blocks():
    backend = RedisBackend(_FakeRedis())
    results = [await backend.is_allowed("k", 2, 60) for _ in range(4)]
    assert results == [True, True, False, False]


# --------------------------- 降级器 ----------------------------


class _BoomRedis:
    """每次调用都抛连接错误，模拟 Redis 不可用。"""

    async def is_allowed(self, *a):
        raise ConnectionError("redis down")


async def test_limiter_memory_only_when_no_redis():
    lim = DegradableRateLimiter(None, InMemoryBackend())
    assert lim.using_redis is False
    results = [await lim.is_allowed("k", 2, 60) for _ in range(3)]
    assert results == [True, True, False]


async def test_limiter_degrades_to_memory_on_failure():
    lim = DegradableRateLimiter(
        _BoomRedis(), InMemoryBackend(), fallback="memory", retry_interval=999
    )
    results = [await lim.is_allowed("k", 2, 60) for _ in range(4)]
    # 降级到内存后仍然限流
    assert results == [True, True, False, False]
    assert lim.using_redis is False


async def test_limiter_fallback_open_lets_all_through():
    lim = DegradableRateLimiter(
        _BoomRedis(), InMemoryBackend(), fallback="open", retry_interval=999
    )
    results = [await lim.is_allowed("k", 1, 60) for _ in range(5)]
    assert all(results)


async def test_limiter_half_open_recovery():
    class _FlakyRedis:
        def __init__(self):
            self.fail = True
            self._inner = InMemoryBackend()

        async def is_allowed(self, key, calls, period):
            if self.fail:
                raise ConnectionError("down")
            return await self._inner.is_allowed(key, calls, period)

    flaky = _FlakyRedis()
    lim = DegradableRateLimiter(
        flaky, InMemoryBackend(), fallback="memory", retry_interval=0
    )
    await lim.is_allowed("k", 10, 60)  # 首次失败 -> 降级
    assert lim.using_redis is False
    flaky.fail = False  # Redis 恢复
    await lim.is_allowed("k", 10, 60)  # retry_interval=0 立即半开重试 -> 成功
    assert lim.using_redis is True


# ----------------------- 中间件端到端 -------------------------


def _request(peer: str, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 1234),
            "scheme": "http",
            "server": ("test", 80),
            "query_string": b"",
            "root_path": "",
        }
    )


def test_untrusted_peer_cannot_spoof_forwarded_ip():
    request = _request("203.0.113.10", [(b"x-forwarded-for", b"1.2.3.4")])
    assert get_client_ip(request, (ip_network("10.0.0.0/8"),)) == "203.0.113.10"


def test_trusted_proxy_chain_selects_first_untrusted_hop_from_right():
    request = _request(
        "10.0.0.2",
        [(b"x-forwarded-for", b"1.2.3.4, 198.51.100.8")],
    )
    assert get_client_ip(request, (ip_network("10.0.0.0/8"),)) == "198.51.100.8"


def _build_app(**mw_kwargs):
    app = FastAPI()
    setup_exception_handlers(app)
    app.add_middleware(ExceptionHandlerMiddleware)  # 最外层，模拟真实 app
    app.add_middleware(RateLimitMiddleware, **mw_kwargs)

    @app.get("/")
    async def root():
        return {"ok": True}

    return app


def test_middleware_returns_429_not_500():
    app = _build_app(calls=3, period=60)
    client = TestClient(app, raise_server_exceptions=False)
    codes = [client.get("/").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]

    resp = client.get("/")
    assert resp.status_code == 429
    body = resp.json()
    assert body["errorCode"] == "RATE_LIMIT_EXCEEDED"
    assert body["statusCode"] == 429
    assert resp.headers["retry-after"] == "60"


def test_auth_middleware_only_limits_configured_paths():
    app = FastAPI()
    setup_exception_handlers(app)
    app.add_middleware(ExceptionHandlerMiddleware)
    app.add_middleware(AuthRateLimitMiddleware, calls=2, period=60)

    @app.get("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    @app.get("/free")
    async def free():
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    # 受限路径：第 3 次被拦
    login_codes = [client.get("/api/v1/auth/login").status_code for _ in range(3)]
    assert login_codes == [200, 200, 429]
    # 非受限路径：永不限流
    free_codes = [client.get("/free").status_code for _ in range(5)]
    assert all(c == 200 for c in free_codes)


def test_health_probe_is_never_rate_limited():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, calls=1, period=60)

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    client = TestClient(app)
    assert [client.get("/health").status_code for _ in range(4)] == [200] * 4
