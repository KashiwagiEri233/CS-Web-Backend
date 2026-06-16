"""带降级能力的限流器。

策略：
- 未配置 Redis：直接用内存后端（行为同旧版）。
- 配置了 Redis：优先走 Redis；任意一次 Redis 调用失败即标记为不健康，
  进入冷却期，期间按 fallback 策略兜底（内存限流或直接放行）；
  冷却期满后半开重试一次 Redis，成功则自动切回。
"""

import time
from typing import Optional

from app.core.config import settings
from app.core.loguru_logger import get_logger
from app.core.rate_limit.backends import InMemoryBackend, RedisBackend
from app.core.redis_client import get_redis_client

logger = get_logger("rate_limit")


class DegradableRateLimiter:
    def __init__(
        self,
        redis_backend: Optional[RedisBackend],
        memory_backend: InMemoryBackend,
        *,
        fallback: str = "memory",
        retry_interval: float = 5.0,
    ) -> None:
        self._redis = redis_backend
        self._memory = memory_backend
        self._fallback = fallback  # "memory" | "open"
        self._retry_interval = retry_interval
        self._healthy = redis_backend is not None
        self._next_retry = 0.0

    @property
    def using_redis(self) -> bool:
        """当前是否正在使用 Redis（已配置且健康）。"""
        return self._redis is not None and self._healthy

    async def is_allowed(self, key: str, calls: int, period: int) -> bool:
        # 未配置 Redis：纯内存模式
        if self._redis is None:
            return await self._memory.is_allowed(key, calls, period)

        now = time.monotonic()

        # 处于降级冷却期：跳过 Redis，直接兜底
        if not self._healthy and now < self._next_retry:
            return await self._fallback_check(key, calls, period)

        try:
            allowed = await self._redis.is_allowed(key, calls, period)
            if not self._healthy:
                logger.info("Redis 限流后端已恢复，切回 Redis")
                self._healthy = True
            return allowed
        except Exception as e:  # noqa: BLE001 - 限流故障绝不能拖垮业务请求
            if self._healthy:
                logger.warning(
                    "Redis 限流后端不可用，自动降级",
                    fallback=self._fallback,
                    retry_after=self._retry_interval,
                    error=str(e),
                )
            self._healthy = False
            self._next_retry = now + self._retry_interval
            return await self._fallback_check(key, calls, period)

    async def _fallback_check(self, key: str, calls: int, period: int) -> bool:
        if self._fallback == "open":
            return True  # 放行：牺牲保护换可用性
        return await self._memory.is_allowed(key, calls, period)


def build_limiter() -> DegradableRateLimiter:
    """根据配置组装限流器。"""
    client = get_redis_client()
    redis_backend = RedisBackend(client) if client is not None else None
    return DegradableRateLimiter(
        redis_backend,
        InMemoryBackend(),
        fallback=settings.RATE_LIMIT_FALLBACK,
        retry_interval=settings.RATE_LIMIT_REDIS_RETRY_INTERVAL,
    )
