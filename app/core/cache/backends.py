"""缓存后端实现。

统一协议（均为 async）：
- get(key) -> Optional[Any]：未命中或已过期返回 None
- set(key, value, ttl) -> None：ttl 为 None 表示不过期

值以 JSON 序列化存入 Redis；因此只支持 JSON 可序列化的值。
"""

import json
import time
from collections import OrderedDict
from typing import Any, Optional, Tuple

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
        if expire_at is not None and expire_at <= time.time():
            self._store.pop(key, None)
            return None
        # 命中时移到末尾，近似 LRU（最近访问的更"热"）
        self._store.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expire_at = time.time() + ttl if ttl else None
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (value, expire_at)
        self._evict_if_needed()

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def _evict_if_needed(self) -> None:
        """超容量时先清过期项，仍有余则淘汰最旧条目。"""
        if len(self._store) <= self._max_entries:
            return
        now = time.time()
        # 第一轮：淘汰所有已过期项
        expired = [k for k, (_, exp) in self._store.items() if exp is not None and exp <= now]
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
        if ttl:
            await self._client.set(key, raw, ex=ttl)
        else:
            await self._client.set(key, raw)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)
