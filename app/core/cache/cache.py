"""带降级能力的通用缓存。

与限流器同样的可用性优先策略：
- 未配置 Redis：直接用内存缓存。
- 配置了 Redis：优先 Redis；任意一次调用失败即标记不健康并进入冷却期，
  期间按 fallback 兜底；冷却期满后半开重试，成功则切回 Redis。

降级策略（fallback）：
- "memory"：Redis 不可用时退回进程内缓存（默认，仍能命中本进程的热数据）。
- "off"：Redis 不可用时 get 恒未命中、set 静默丢弃（缓存视为可有可无）。

缓存的语义本就是"尽力而为"：任何后端异常都不会向调用方抛出，最差也只是未命中。
"""

import functools
import hashlib
import time
from typing import Any, Callable, Optional

from app.core.config import settings
from app.core.loguru_logger import get_logger
from app.core.cache.backends import InMemoryCacheBackend, RedisCacheBackend
from app.core.redis_client import get_redis_client

logger = get_logger("cache")


class DegradableCache:
    def __init__(
        self,
        redis_backend: Optional[RedisCacheBackend],
        memory_backend: InMemoryCacheBackend,
        *,
        fallback: str = "memory",
        retry_interval: float = 5.0,
    ) -> None:
        self._redis = redis_backend
        self._memory = memory_backend
        self._fallback = fallback  # "memory" | "off"
        self._retry_interval = retry_interval
        self._healthy = redis_backend is not None
        self._next_retry = 0.0

    @property
    def using_redis(self) -> bool:
        return self._redis is not None and self._healthy

    async def get(self, key: str) -> Optional[Any]:
        if self._redis is None:
            return await self._memory.get(key)
        if not self._healthy and time.monotonic() < self._next_retry:
            return await self._fallback_get(key)
        try:
            result = await self._redis.get(key)
            self._mark_healthy()
            return result
        except Exception as e:  # noqa: BLE001 - 缓存故障绝不向上抛
            self._mark_unhealthy(e)
            return await self._fallback_get(key)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if self._redis is None:
            await self._memory.set(key, value, ttl)
            return
        if not self._healthy and time.monotonic() < self._next_retry:
            await self._fallback_set(key, value, ttl)
            return
        try:
            await self._redis.set(key, value, ttl)
            self._mark_healthy()
        except Exception as e:  # noqa: BLE001
            self._mark_unhealthy(e)
            await self._fallback_set(key, value, ttl)

    async def delete(self, key: str) -> None:
        if self._redis is None:
            await self._memory.delete(key)
            return
        # 与 get/set 一致的冷却短路：故障期内不再白等一个 socket 超时
        if not self._healthy and time.monotonic() < self._next_retry:
            await self._memory.delete(key)
            return
        try:
            await self._redis.delete(key)
            self._mark_healthy()
        except Exception as e:  # noqa: BLE001
            self._mark_unhealthy(e)
        # 无论 Redis 是否成功，都清掉内存兜底里的同名键，避免脏读
        await self._memory.delete(key)

    # ----------------------- 内部 -----------------------

    def _mark_healthy(self) -> None:
        if not self._healthy:
            logger.info("Redis 缓存后端已恢复，切回 Redis")
            self._healthy = True

    def _mark_unhealthy(self, error: Exception) -> None:
        if self._healthy:
            logger.warning(
                "Redis 缓存后端不可用，自动降级",
                fallback=self._fallback,
                retry_after=self._retry_interval,
                error=str(error),
            )
        self._healthy = False
        self._next_retry = time.monotonic() + self._retry_interval

    async def _fallback_get(self, key: str) -> Optional[Any]:
        if self._fallback == "off":
            return None
        return await self._memory.get(key)

    async def _fallback_set(self, key: str, value: Any, ttl: Optional[int]) -> None:
        if self._fallback == "off":
            return
        await self._memory.set(key, value, ttl)


def build_cache() -> DegradableCache:
    client = get_redis_client()
    redis_backend = RedisCacheBackend(client) if client is not None else None
    return DegradableCache(
        redis_backend,
        InMemoryCacheBackend(),
        fallback=settings.CACHE_FALLBACK,
        retry_interval=settings.RATE_LIMIT_REDIS_RETRY_INTERVAL,
    )


_cache: Optional[DegradableCache] = None


def get_cache() -> DegradableCache:
    """全局缓存单例。"""
    global _cache
    if _cache is None:
        _cache = build_cache()
    return _cache


def cached(ttl: Optional[int] = None, key_prefix: str = "") -> Callable:
    """缓存异步函数返回值的装饰器。

    缓存键由 key_prefix + 函数限定名 + 位置/关键字参数派生。
    仅适用于参数可 repr 且返回值 JSON 可序列化的场景。

    注意：
    - 返回 None 的结果不会被缓存（None 与"未命中"同值，无法区分）；
      返回 None 的热函数会每次穿透回源，调用方需自行评估是否接受。
    - 无 single-flight：缓存击穿瞬间并发请求会同时回源，后端需能承受。

    Args:
        ttl: 过期秒数，None 表示不过期。
        key_prefix: 键前缀（建议按业务域区分，便于排查与失效）。
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            prefix = key_prefix or func.__qualname__
            raw_key = f"{func.__qualname__}|{args!r}|{sorted(kwargs.items())!r}"
            digest = hashlib.md5(raw_key.encode("utf-8")).hexdigest()
            cache_key = f"cache:{prefix}:{digest}"

            cache = get_cache()
            hit = await cache.get(cache_key)
            if hit is not None:
                return hit

            result = await func(*args, **kwargs)
            if result is not None:
                await cache.set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator
