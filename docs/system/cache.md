# 缓存

## 概述

`app/core/cache/` 提供异步键值缓存。配置 Redis 时使用共享后端；未配置或 Redis
故障时按 `CACHE_FALLBACK` 降级到有容量上限的进程内缓存。

## 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_cache` | `get_cache() -> DegradableCache` | 获取进程级缓存门面 |
| `DegradableCache.get` | `await get(key)` | 读取并反序列化值 |
| `DegradableCache.set` | `await set(key, value, ttl=None)` | 写入值和可选 TTL |
| `DegradableCache.delete` | `await delete(key)` | 删除键 |
| `cached` | `@cached(ttl, key_prefix)` | 缓存异步函数结果 |

## 配置

| 配置 | 默认 | 说明 |
|---|---:|---|
| `REDIS_URL` | 空 | 空时使用内存后端 |
| `CACHE_FALLBACK` | `memory` | Redis 故障后使用 `memory` 或 `off` |
| `CACHE_REDIS_RETRY_INTERVAL` | 30 | 熔断后尝试恢复 Redis 的秒数 |
| `CACHE_MAX_ENTRIES` | 10000 | 内存缓存容量上限 |

## 降级与不变量

- Redis 写失败后进入降级态；冷却期满执行半开探测，成功后恢复。
- 内存缓存不跨 worker 共享，不能用于需要全局一致性的状态。
- 缓存只能提升性能，业务正确性不能依赖缓存命中。

## 测试

- `tests/core/test_cache.py`：TTL、容量、降级和恢复。
- `tests/integration/test_redis_backends.py`：真实 Redis JSON 往返和故障恢复。

## 扩展指引

新增缓存场景优先复用 `get_cache()`；键必须带业务前缀，并为可失效数据设置 TTL。

