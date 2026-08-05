"""access token 黑名单后端测试（不依赖 DB / Redis）。

覆盖：
- 未配置 Redis：纯内存路径，add/contains/TTL 过期。
- fallback="open"：故障时不视为黑名单。
- fallback="closed"：故障时拒绝 token。
- fallback="memory"：故障时回退内存。
- 半开恢复：冷却期满后切回 Redis（用 mock 模拟）。
"""

import asyncio
import time

from app.core.security_blacklist import TokenBlacklist, _MemoryBlacklist


def test_memory_add_and_contains():
    bl = _MemoryBlacklist()
    bl.add("jti-1", ttl_seconds=60)
    assert bl.contains("jti-1")
    assert not bl.contains("jti-2")


def test_memory_ttl_expiry():
    bl = _MemoryBlacklist()
    bl.add("jti-expire", ttl_seconds=1)
    assert bl.contains("jti-expire")
    # 等待过期（单调时钟 lazy 清理）
    time.sleep(1.1)
    assert not bl.contains("jti-expire")


def test_memory_zero_ttl_is_noop():
    bl = _MemoryBlacklist()
    bl.add("jti-zero", ttl_seconds=0)
    assert not bl.contains("jti-zero")


async def test_blacklist_no_redis_uses_memory():
    """未配置 Redis（client=None）：纯内存路径。"""
    bl = TokenBlacklist(None, _MemoryBlacklist(), fallback="memory")
    assert not bl.using_redis
    await bl.add("jti-a", 60)
    assert await bl.contains("jti-a")
    assert not await bl.contains("jti-other")


class _FlakyRedis:
    """可控失败的假 Redis，用于测试降级与恢复。"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.store: dict[str, str] = {}

    async def setex(self, key, ttl, val):
        if self.fail:
            raise RuntimeError("redis down")
        self.store[key] = val

    async def exists(self, key):
        if self.fail:
            raise RuntimeError("redis down")
        return 1 if key in self.store else 0


async def test_blacklist_redis_healthy_path():
    redis = _FlakyRedis(fail=False)
    bl = TokenBlacklist(redis, _MemoryBlacklist(), fallback="memory")
    assert bl.using_redis
    await bl.add("jti-healthy", 60)
    # Redis 与内存双写
    assert await bl.contains("jti-healthy")


async def test_blacklist_falls_back_to_memory_on_failure():
    redis = _FlakyRedis(fail=True)
    mem = _MemoryBlacklist()
    bl = TokenBlacklist(redis, mem, fallback="memory")
    # Redis 故障 → 降级写入内存
    await bl.add("jti-down", 60)
    assert not bl.using_redis
    # 查询：Redis 故障 → 走内存兜底
    assert await bl.contains("jti-down")


async def test_blacklist_fallback_open_lets_through():
    redis = _FlakyRedis(fail=True)
    mem = _MemoryBlacklist()
    bl = TokenBlacklist(redis, mem, fallback="open")
    await bl.add("jti-open", 60)  # 写：Redis 故障，因 fallback=open 不写内存
    # 查询：Redis 故障 → open 放行 → False（不在黑名单）
    assert not await bl.contains("jti-open")


async def test_blacklist_fallback_closed_denies_when_redis_is_missing():
    bl = TokenBlacklist(None, _MemoryBlacklist(), fallback="closed")
    assert await bl.contains("any-jti")


async def test_blacklist_half_open_recovery():
    """Redis 故障冷却期满后恢复。"""
    redis = _FlakyRedis(fail=True)
    bl = TokenBlacklist(
        redis, _MemoryBlacklist(), fallback="memory", retry_interval=0.1
    )
    # 触发降级
    await bl.add("jti-1", 60)
    assert not bl.using_redis

    # 冷却期内：仍降级
    await bl.add("jti-2", 60)
    assert not bl.using_redis

    # 冷却期满 + Redis 恢复
    await asyncio.sleep(0.15)
    redis.fail = False
    await bl.add("jti-3", 60)
    assert bl.using_redis, "冷却期满后 Redis 恢复应切回"


async def test_blacklist_rechecks_memory_after_redis_recovery():
    """回归：降级窗口内拉黑的 jti，Redis 恢复后仍应命中（防恢复瞬间 fail-open）。"""
    redis = _FlakyRedis(fail=True)
    bl = TokenBlacklist(
        redis, _MemoryBlacklist(), fallback="memory", retry_interval=0.1
    )
    # 降级窗口：只能写内存（Redis 无此 key）
    await bl.add("jti-during-outage", 60)
    assert not bl.using_redis

    # 冷却期满 + Redis 恢复：Redis 未命中时必须回查内存
    await asyncio.sleep(0.15)
    redis.fail = False
    assert await bl.contains("jti-during-outage")
    assert bl.using_redis


async def test_blacklist_open_fallback_ignores_memory_after_recovery():
    """fallback=open 尊重可用性优先：恢复后只信 Redis，不回查内存。"""
    redis = _FlakyRedis(fail=True)
    bl = TokenBlacklist(redis, _MemoryBlacklist(), fallback="open", retry_interval=0.1)
    await bl.add("jti-open-outage", 60)

    await asyncio.sleep(0.15)
    redis.fail = False
    assert not await bl.contains("jti-open-outage")
