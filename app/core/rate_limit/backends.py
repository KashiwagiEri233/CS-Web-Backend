"""限流后端实现。

两种后端实现统一的 `is_allowed(key, calls, period)` 协议：
在 period 秒的滑动窗口内，若 key 的请求数已达 calls 则拒绝（返回 False），
否则记录本次请求并放行（返回 True）。
"""

import time
import uuid
from collections import defaultdict
from typing import Dict, List

# 内存限流最大跟踪 key 数。超过后清理已过期/空的 key，防止大量一次性 IP 导致 OOM。
_DEFAULT_MAX_KEYS = 100000


class InMemoryBackend:
    """进程内滑动窗口限流（带容量清理）。

    用于：未配置 Redis 的单实例部署，或 Redis 故障时的降级兜底。
    局限：状态不跨进程/实例共享（多 worker 各自计数）。
    """

    def __init__(self, max_keys: int = _DEFAULT_MAX_KEYS) -> None:
        self._hits: Dict[str, List[float]] = defaultdict(list)
        self._max_keys = max_keys

    async def is_allowed(self, key: str, calls: int, period: int) -> bool:
        now = time.time()
        cutoff = now - period
        # 清理窗口外的旧记录
        kept = [ts for ts in self._hits[key] if ts > cutoff]

        if len(kept) >= calls:
            self._hits[key] = kept
            return False

        kept.append(now)
        self._hits[key] = kept
        # 周期性清理：超 key 上限时移除已过期的空 key，防止无界增长
        if len(self._hits) > self._max_keys:
            self._purge_expired_keys(cutoff)
        return True

    def _purge_expired_keys(self, cutoff: float) -> None:
        """移除窗口已全部过期的 key（清理后为空的 key）。"""
        empty_keys = [k for k, hits in self._hits.items() if not any(ts > cutoff for ts in hits)]
        for k in empty_keys:
            self._hits.pop(k, None)


# 滑动窗口日志算法，整段在 Redis 内原子执行，避免并发竞态：
#   1. 移除窗口外的旧成员
#   2. 统计当前窗口内请求数，达到上限则拒绝
#   3. 否则写入本次请求（唯一成员）并续期过期时间
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window + 1)
return 1
"""


class RedisBackend:
    """基于 Redis ZSET 的跨实例滑动窗口限流。

    任意一次 Redis 调用失败（连接/超时等）都会向上抛出异常，
    由 DegradableRateLimiter 捕获并降级——本类自身不做兜底。
    """

    def __init__(self, client) -> None:
        self._client = client
        self._script = None  # 懒注册 Lua 脚本

    async def is_allowed(self, key: str, calls: int, period: int) -> bool:
        if self._script is None:
            self._script = self._client.register_script(_SLIDING_WINDOW_LUA)

        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"
        result = await self._script(keys=[key], args=[now, period, calls, member])
        return bool(int(result))
