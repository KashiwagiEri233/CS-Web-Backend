"""带降级能力的通用缓存测试。不依赖真实 Redis / 数据库。"""

import time

from app.core.cache.backends import InMemoryCacheBackend, RedisCacheBackend
from app.core.cache.cache import DegradableCache, cached
import app.core.cache.cache as cache_module


# --------------------------- 内存后端 ---------------------------

async def test_memory_get_set_delete():
    c = InMemoryCacheBackend()
    assert await c.get("k") is None
    await c.set("k", {"a": 1})
    assert await c.get("k") == {"a": 1}
    await c.delete("k")
    assert await c.get("k") is None


async def test_memory_ttl_expiry(monkeypatch):
    c = InMemoryCacheBackend()
    t = {"now": 1000.0}
    monkeypatch.setattr(time, "time", lambda: t["now"])
    await c.set("k", "v", ttl=10)
    assert await c.get("k") == "v"
    t["now"] += 11
    assert await c.get("k") is None


# --------------------------- Redis 后端 --------------------------

class _FakeRedisClient:
    """最小内存版 Redis，仅覆盖 get/set/delete 的调用约定。"""

    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)


async def test_redis_backend_json_roundtrip():
    backend = RedisCacheBackend(_FakeRedisClient())
    await backend.set("k", {"x": [1, 2, 3]})
    assert await backend.get("k") == {"x": [1, 2, 3]}
    await backend.delete("k")
    assert await backend.get("k") is None


# --------------------------- 降级器 -----------------------------

class _BoomRedis:
    async def get(self, *a):
        raise ConnectionError("down")

    async def set(self, *a):
        raise ConnectionError("down")

    async def delete(self, *a):
        raise ConnectionError("down")


async def test_cache_memory_only_when_no_redis():
    cache = DegradableCache(None, InMemoryCacheBackend())
    assert cache.using_redis is False
    await cache.set("k", 123)
    assert await cache.get("k") == 123


async def test_cache_degrades_to_memory():
    cache = DegradableCache(
        _BoomRedis(), InMemoryCacheBackend(), fallback="memory", retry_interval=999
    )
    await cache.set("k", "v")           # Redis 抛错 -> 降级写内存
    assert cache.using_redis is False
    assert await cache.get("k") == "v"  # 从内存兜底命中


async def test_cache_fallback_off_is_noop():
    cache = DegradableCache(
        _BoomRedis(), InMemoryCacheBackend(), fallback="off", retry_interval=999
    )
    await cache.set("k", "v")           # 静默丢弃
    assert await cache.get("k") is None  # 恒未命中


async def test_cache_half_open_recovery():
    class _FlakyRedis:
        def __init__(self):
            self.fail = True
            self._inner = InMemoryCacheBackend()

        async def get(self, key):
            if self.fail:
                raise ConnectionError("down")
            return await self._inner.get(key)

        async def set(self, key, value, ttl=None):
            if self.fail:
                raise ConnectionError("down")
            await self._inner.set(key, value, ttl)

        async def delete(self, key):
            await self._inner.delete(key)

    flaky = _FlakyRedis()
    cache = DegradableCache(
        flaky, InMemoryCacheBackend(), fallback="memory", retry_interval=0
    )
    await cache.get("k")                 # 失败 -> 降级
    assert cache.using_redis is False
    flaky.fail = False
    await cache.get("k")                 # 半开重试成功 -> 切回
    assert cache.using_redis is True


# --------------------------- 装饰器 -----------------------------

async def test_cached_decorator_memoizes(monkeypatch):
    # 用一个全新的纯内存缓存替换全局单例，隔离测试
    monkeypatch.setattr(
        cache_module, "_cache", DegradableCache(None, InMemoryCacheBackend())
    )

    calls = {"n": 0}

    @cached(ttl=60, key_prefix="t")
    async def compute(x, y=0):
        calls["n"] += 1
        return x + y

    assert await compute(2, y=3) == 5
    assert await compute(2, y=3) == 5      # 命中缓存
    assert calls["n"] == 1                  # 底层只执行一次
    assert await compute(2, y=4) == 6      # 参数不同 -> 重新计算
    assert calls["n"] == 2
