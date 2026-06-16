"""带降级能力的通用缓存子系统。

用法：
    from app.core.cache import get_cache
    cache = get_cache()
    await cache.set("user:1", {"name": "x"}, ttl=60)
    data = await cache.get("user:1")

或用装饰器缓存异步函数返回值：
    from app.core.cache import cached

    @cached(ttl=60, key_prefix="profile")
    async def get_profile(user_id: int):
        ...
"""

from app.core.cache.backends import InMemoryCacheBackend, RedisCacheBackend
from app.core.cache.cache import DegradableCache, build_cache, get_cache, cached

__all__ = [
    "InMemoryCacheBackend",
    "RedisCacheBackend",
    "DegradableCache",
    "build_cache",
    "get_cache",
    "cached",
]
