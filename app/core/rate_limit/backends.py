"""限流后端实现。

两种后端实现统一的 `is_allowed(key, calls, period)` 协议：
在 period 秒的滑动窗口内，若 key 的请求数已达 calls 则拒绝（返回 False），
否则记录本次请求并放行（返回 True）。
"""

import time
import uuid
from collections import defaultdict
from typing import Dict, List


class InMemoryBackend:
    """进程内滑动窗口限流。

    用于：未配置 Redis 的单实例部署，或 Redis 故障时的降级兜底。
    局限：状态不跨进程/实例共享（多 worker 各自计数）。
    """

    def __init__(self) -> None:
        self._hits: Dict[str, List[float]] = defaultdict(list)

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
        return True


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
