"""缓存后端实现。

统一协议（均为 async）：
- get(key) -> Optional[Any]：未命中或已过期返回 None
- set(key, value, ttl) -> None：ttl 为 None 表示不过期
- delete(key) -> None

值以 JSON 序列化存入 Redis；因此只支持 JSON 可序列化的值。
"""

import json
import time
from typing import Any, Dict, Optional, Tuple


class InMemoryCacheBackend:
    """进程内 TTL 缓存。

    用于：未配置 Redis 的单实例部署，或 Redis 故障时的降级兜底。
    局限：不跨进程/实例共享，且无容量上限（仅在访问时清理过期项）。
    """

    def __init__(self) -> None:
        self._store: Dict[str, Tuple[Any, Optional[float]]] = {}

    async def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if item is None:
            return None
        value, expire_at = item
        if expire_at is not None and expire_at <= time.time():
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expire_at = time.time() + ttl if ttl else None
        self._store[key] = (value, expire_at)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


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
