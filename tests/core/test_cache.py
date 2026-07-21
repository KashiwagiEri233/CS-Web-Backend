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
    # 内存缓存过期用单调时钟（防系统时钟回拨），测试同步 patch monotonic
    monkeypatch.setattr(time, "monotonic", lambda: t["now"])
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
    await cache.set("k", "v")  # Redis 抛错 -> 降级写内存
    assert cache.using_redis is False
    assert await cache.get("k") == "v"  # 从内存兜底命中


async def test_cache_fallback_off_is_noop():
    cache = DegradableCache(
        _BoomRedis(), InMemoryCacheBackend(), fallback="off", retry_interval=999
    )
    await cache.set("k", "v")  # 静默丢弃
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
    await cache.get("k")  # 失败 -> 降级
    assert cache.using_redis is False
    flaky.fail = False
    await cache.get("k")  # 半开重试成功 -> 切回
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
    assert await compute(2, y=3) == 5  # 命中缓存
    assert calls["n"] == 1  # 底层只执行一次
    assert await compute(2, y=4) == 6  # 参数不同 -> 重新计算
    assert calls["n"] == 2


# --------------------------- 容量上限（#28） ---------------------


async def test_memory_cache_evicts_when_full():
    """超 max_entries 时应淘汰过期项，仍有余则淘汰最旧条目。"""
    c = InMemoryCacheBackend(max_entries=3)
    await c.set("k1", "v1", ttl=100)
    await c.set("k2", "v2", ttl=100)
    await c.set("k3", "v3", ttl=100)
    # 写入第 4 个，应触发淘汰（k1 最旧）
    await c.set("k4", "v4", ttl=100)
    assert await c.get("k1") is None
    assert await c.get("k4") == "v4"
    # 容量不超限
    assert len(c._store) <= 3


async def test_memory_cache_evicts_expired_first():
    """淘汰时优先清理已过期项，保留未过期的。"""
    import time as _time

    c = InMemoryCacheBackend(max_entries=3)
    # k1 已过期
    await c.set("k1", "v1", ttl=1)
    _time.sleep(1.1)
    # k2、k3 未过期
    await c.set("k2", "v2", ttl=100)
    await c.set("k3", "v3", ttl=100)
    # 写入第 4 个：先清过期（k1），k2/k3 保留
    await c.set("k4", "v4", ttl=100)
    assert await c.get("k1") is None
    assert await c.get("k2") == "v2"
    assert await c.get("k3") == "v3"


async def test_memory_cache_lru_on_get():
    """get 命中后该 key 应视为"热"，不被优先淘汰。"""
    c = InMemoryCacheBackend(max_entries=3)
    await c.set("a", 1, ttl=100)
    await c.set("b", 2, ttl=100)
    await c.set("c", 3, ttl=100)
    # 访问 a，使其移到末尾（变热）
    await c.get("a")
    # 写入 d，应淘汰最旧的 b（a 因被访问过更热）
    await c.set("d", 4, ttl=100)
    assert await c.get("a") == 1
    assert await c.get("b") is None
