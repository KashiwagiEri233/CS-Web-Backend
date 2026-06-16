"""access token 黑名单（可降级，与限流/缓存一致的高可用策略）。

用途：登出、改密后让尚未过期的 access token 立即失效。
- 未配置 Redis：纯进程内 TTL 字典（单实例可见）。
- 配置了 Redis：跨实例一致；任意一次调用失败进入冷却期，期间按 fallback 兜底。
- fallback="memory"（默认）：故障时回退内存（单进程保护）。
- fallback="open"：Redis 故障时放行（牺牲保护换可用性，不推荐）。

黑名单语义：key = access token 的 jti，value 占位。TTL = 该 access token 的剩余有效期，
token 自然过期后条目自动清理，避免无限增长。
"""

import time
from typing import Optional

from app.core.config import settings
from app.core.loguru_logger import get_logger
from app.core.redis_client import get_redis_client

logger = get_logger("token_blacklist")

_REDIS_KEY_PREFIX = "jwt:blacklist:"


class _MemoryBlacklist:
    """进程内 TTL 黑名单。lazy 清理过期项，避免后台线程。"""

    def __init__(self) -> None:
        self._store: dict[str, float] = {}  # jti -> expire_monotonic

    def add(self, jti: str, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        self._store[jti] = time.monotonic() + ttl_seconds

    def contains(self, jti: str) -> bool:
        exp = self._store.get(jti)
        if exp is None:
            return False
        if time.monotonic() >= exp:
            # lazy 清理
            self._store.pop(jti, None)
            return False
        return True


class TokenBlacklist:
    def __init__(
        self,
        redis_client,
        memory_backend: _MemoryBlacklist,
        *,
        fallback: str = "memory",
        retry_interval: float = 5.0,
    ) -> None:
        self._redis = redis_client
        self._memory = memory_backend
        self._fallback = fallback
        self._retry_interval = retry_interval
        self._healthy = redis_client is not None
        self._next_retry = 0.0

    @property
    def using_redis(self) -> bool:
        return self._redis is not None and self._healthy

    async def add(self, jti: str, ttl_seconds: int) -> None:
        """把 jti 加入黑名单。失败绝不抛出（黑名单是安全增强，不是强依赖）。"""
        if self._redis is None:
            self._memory.add(jti, ttl_seconds)
            return
        if not self._healthy and time.monotonic() < self._next_retry:
            self._memory.add(jti, ttl_seconds)
            return
        try:
            await self._redis.setex(
                f"{_REDIS_KEY_PREFIX}{jti}", ttl_seconds, "1"
            )
            self._mark_healthy()
            # Redis 与内存双写：Redis 故障降级期间内存里仍能命中本进程的登出
            self._memory.add(jti, ttl_seconds)
        except Exception as e:  # noqa: BLE001 - 黑名单故障绝不阻塞业务
            self._mark_unhealthy(e)
            self._memory.add(jti, ttl_seconds)

    async def contains(self, jti: str) -> bool:
        """jti 是否在黑名单中。失败按 fallback 兜底。"""
        if self._redis is None:
            return self._memory.contains(jti)
        if not self._healthy and time.monotonic() < self._next_retry:
            return self._fallback_contains(jti)
        try:
            hit = await self._redis.exists(f"{_REDIS_KEY_PREFIX}{jti}")
            self._mark_healthy()
            return bool(hit)
        except Exception as e:  # noqa: BLE001
            self._mark_unhealthy(e)
            return self._fallback_contains(jti)

    # ----------------------- 内部 -----------------------

    def _mark_healthy(self) -> None:
        if not self._healthy:
            logger.info("Redis 黑名单后端已恢复，切回 Redis")
            self._healthy = True

    def _mark_unhealthy(self, error: Exception) -> None:
        if self._healthy:
            logger.warning(
                "Redis 黑名单后端不可用，自动降级",
                fallback=self._fallback,
                retry_after=self._retry_interval,
                error=str(error),
            )
        self._healthy = False
        self._next_retry = time.monotonic() + self._retry_interval

    def _fallback_contains(self, jti: str) -> bool:
        if self._fallback == "open":
            return False  # 放行：Redis 故障时不视为黑名单
        return self._memory.contains(jti)


_blacklist: Optional[TokenBlacklist] = None


def get_blacklist() -> TokenBlacklist:
    """全局黑名单单例。"""
    global _blacklist
    if _blacklist is None:
        _blacklist = TokenBlacklist(
            get_redis_client(),
            _MemoryBlacklist(),
            fallback=settings.TOKEN_BLACKLIST_FALLBACK,
            retry_interval=settings.RATE_LIMIT_REDIS_RETRY_INTERVAL,
        )
    return _blacklist
