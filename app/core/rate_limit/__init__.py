"""带降级能力的限流子系统。

- InMemoryBackend：进程内滑动窗口，单实例 / 降级兜底使用
- RedisBackend：基于 Redis ZSET 的滑动窗口，跨实例一致
- DegradableRateLimiter：优先 Redis，故障时自动降级并半开重试
- build_limiter：根据配置组装限流器
"""

from app.core.rate_limit.backends import InMemoryBackend, RedisBackend
from app.core.rate_limit.limiter import DegradableRateLimiter, build_limiter

__all__ = [
    "InMemoryBackend",
    "RedisBackend",
    "DegradableRateLimiter",
    "build_limiter",
]
