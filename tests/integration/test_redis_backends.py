"""真实 Redis 集成测试：缓存、限流、黑名单以及故障恢复。"""

from __future__ import annotations

import uuid

import pytest

from app.core.cache.backends import InMemoryCacheBackend, RedisCacheBackend
from app.core.cache.cache import DegradableCache
from app.core.rate_limit.backends import RedisBackend
from app.core.security_blacklist import TokenBlacklist, _MemoryBlacklist

pytestmark = pytest.mark.integration


async def test_real_redis_cache_roundtrip(integration_redis_client):
    key = f"itest:cache:{uuid.uuid4().hex}"
    backend = RedisCacheBackend(integration_redis_client)
    try:
        await backend.set(key, {"ok": True, "items": [1, 2]}, ttl=30)
        assert await backend.get(key) == {"ok": True, "items": [1, 2]}
        await backend.delete(key)
        assert await backend.get(key) is None
    finally:
        await integration_redis_client.delete(key)


async def test_real_redis_rate_limit_is_atomic(integration_redis_client):
    key = f"itest:rate:{uuid.uuid4().hex}"
    backend = RedisBackend(integration_redis_client)
    try:
        results = [await backend.is_allowed(key, calls=2, period=30) for _ in range(3)]
        assert results == [True, True, False]
    finally:
        await integration_redis_client.delete(key)


async def test_real_redis_token_blacklist(integration_redis_client):
    jti = f"itest-{uuid.uuid4().hex}"
    backend_key = f"token_blacklist:{jti}"
    blacklist = TokenBlacklist(
        integration_redis_client, _MemoryBlacklist(), fallback="memory"
    )
    try:
        await blacklist.add(jti, 30)
        assert await blacklist.contains(jti)
        assert blacklist.using_redis
    finally:
        await integration_redis_client.delete(backend_key)


class _ToggleRedis:
    """故障注入包装器；恢复后仍调用真实 Redis。"""

    def __init__(self, client) -> None:
        self.client = client
        self.failed = True

    async def get(self, key):
        if self.failed:
            raise ConnectionError("injected redis outage")
        return await self.client.get(key)

    async def set(self, key, value, ex=None):
        if self.failed:
            raise ConnectionError("injected redis outage")
        return await self.client.set(key, value, ex=ex)

    async def delete(self, key):
        if self.failed:
            raise ConnectionError("injected redis outage")
        return await self.client.delete(key)


async def test_cache_recovers_from_failure_to_real_redis(integration_redis_client):
    key = f"itest:recover:{uuid.uuid4().hex}"
    toggle = _ToggleRedis(integration_redis_client)
    cache = DegradableCache(
        toggle,
        InMemoryCacheBackend(),
        fallback="memory",
        retry_interval=0,
    )
    try:
        await cache.set(key, "fallback")
        assert not cache.using_redis
        assert await cache.get(key) == "fallback"

        toggle.failed = False
        await cache.set(key, "redis")
        assert cache.using_redis
        assert await cache.get(key) == "redis"
    finally:
        toggle.failed = False
        await integration_redis_client.delete(key)
