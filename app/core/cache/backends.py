"""缓存后端实现。

统一协议（均为 async）：
- get(key) -> Optional[Any]：未命中或已过期返回 None
- set(key, value, ttl) -> None：ttl 为 None 表示不过期

值以 JSON 序列化存入 Redis；因此只支持 JSON 可序列化的值。
"""

import json
import time
from collections import OrderedDict
from typing import Any, Optional, Sequence, Tuple

# 内存缓存默认最大条目数。超过后触发清理（淘汰过期项 + 最旧未过期项），
# 防止 Redis 长期故障降级时无界增长导致 OOM。
_DEFAULT_MAX_ENTRIES = 10000


class InMemoryCacheBackend:
    """进程内 TTL 缓存（带容量上限）。

    用于：未配置 Redis 的单实例部署，或 Redis 故障时的降级兜底。
    局限：不跨进程/实例共享。容量超 max_entries 时，先清理过期项，
    仍有余则淘汰最旧条目（近似 LRU，借助 OrderedDict 的插入顺序）。
    """

    def __init__(self, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self._store: OrderedDict[str, Tuple[Any, Optional[float]]] = OrderedDict()
        self._max_entries = max_entries

    async def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if item is None:
            return None
        value, expire_at = item
        if expire_at is not None and expire_at <= time.monotonic():
            self._store.pop(key, None)
            return None
        # 命中时移到末尾，近似 LRU（最近访问的更"热"）
        self._store.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        # ttl=None 不过期；ttl<=0 立即过期（注意不能用真值判断，否则 ttl=0 会变成永不过期）
        expire_at = None if ttl is None else time.monotonic() + max(ttl, 0)
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (value, expire_at)
        self._evict_if_needed()

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_many(self, keys: Sequence[str]) -> None:
        for key in keys:
            self._store.pop(key, None)

    async def incr(self, key: str, amount: int = 1) -> int:
        """进程内原子自增（单事件循环，无需锁）。"""
        current, expire_at = self._store.get(key, (0, None))
        if not isinstance(current, int):
            current = 0
        new_value = current + amount
        self._store[key] = (new_value, expire_at)
        return new_value

    async def getset(self, key: str, value: Any) -> Any:
        """进程内「取旧值并设为新值」。"""
        item = self._store.get(key)
        old = item[0] if item is not None else None
        self._store[key] = (value, None)
        return old

    async def expire(self, key: str, ttl: int) -> None:
        """进程内设置过期时间（秒）；ttl<=0 视为不设置。"""
        if ttl is None or ttl <= 0:
            return
        item = self._store.get(key)
        if item is not None:
            self._store[key] = (item[0], time.monotonic() + ttl)

    def _evict_if_needed(self) -> None:
        """超容量时先清过期项，仍有余则淘汰最旧条目。"""
        if len(self._store) <= self._max_entries:
            return
        now = time.monotonic()
        # 第一轮：淘汰所有已过期项
        expired = [
            k for k, (_, exp) in self._store.items() if exp is not None and exp <= now
        ]
        for k in expired:
            self._store.pop(k, None)
        # 第二轮：若仍超限，淘汰最旧条目（OrderedDict 首元素）
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)


class RedisCacheBackend:
    """基于 Redis 的缓存。任意 Redis 调用失败都向上抛出，由 DegradableCache 兜底。"""

    def __init__(self, client) -> None:
        self._client = client

    async def get(self, key: str) -> Optional[Any]:
        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw  # 非 JSON 值原样返回，兼容外部写入

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        if ttl is None:
            await self._client.set(key, raw)
        elif ttl <= 0:
            # 立即过期语义：等价于不缓存（setex 不接受 0/负数）
            await self._client.delete(key)
        else:
            await self._client.set(key, raw, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def delete_many(self, keys: Sequence[str]) -> None:
        """一次 DEL 删除多个键：批量失效不应退化成 N 次串行往返。"""
        if keys:
            await self._client.delete(*keys)

    async def incr(self, key: str, amount: int = 1) -> int:
        """原子自增，返回自增后的值（Redis INCR/INCRBY）。

        用于计数类场景（如浏览计数）：并发自增不会丢计数。
        """
        return await self._client.incr(key, amount)

    async def getset(self, key: str, value: Any) -> Any:
        """原子「取旧值并设为新值」（Redis GETSET），未命中返回 None。

        用于计数落库时把计数器原子清零：取到的旧值即本次需落库的增量。
        """
        raw = await self._client.getset(key, json.dumps(value, ensure_ascii=False, default=str))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw

    async def expire(self, key: str, ttl: int) -> None:
        """设置过期时间（秒）；ttl<=0 视为不设置。"""
        if ttl is None or ttl <= 0:
            return
        await self._client.expire(key, ttl)
