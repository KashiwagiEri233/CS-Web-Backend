# 请求限流

## 概述

限流后端优先使用 Redis，以便多实例共享计数；未配置 Redis 或 Redis 故障时降级为进程内存。
全局限流覆盖所有请求，认证限流额外覆盖登录、注册和 refresh 端点。

代码：`app/core/rate_limit/`、`app/middleware/rate_limit.py`。

## 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_client_ip` | `get_client_ip(request, trusted_proxies=()) -> str` | 从可信代理链解析真实客户端 IP |
| `RateLimitMiddleware` | `RateLimitMiddleware(app, calls, period, limit_paths=None)` | 全局或指定路径限流 |
| `AuthRateLimitMiddleware` | `AuthRateLimitMiddleware(app, calls, period)` | 认证端点严格限流 |

超限直接返回统一的 `429` JSON 响应和 `Retry-After`，中间件不抛 `HTTPException`。

## 配置

- `RATE_LIMIT_CALLS` / `RATE_LIMIT_PERIOD`：全局窗口。
- `AUTH_RATE_LIMIT_CALLS` / `AUTH_RATE_LIMIT_PERIOD`：认证窗口。
- `TRUSTED_PROXY_CIDRS`：逗号分隔的可信反向代理 CIDR；为空时忽略 `X-Forwarded-For` 和 `X-Real-IP`。
- `REDIS_URL` 及 Redis 超时/重试配置：控制共享后端和故障降级。

只有直连来源处于可信网段时才读取转发头，并从右向左跳过可信代理，取第一个不可信地址。
部署在反向代理后时应填写实际代理网段，不要使用过宽的公网网段。

## 降级与不变量

- Redis 是增强项，不是启动依赖；故障后限流退化为单进程语义。
- 不可信来源提供的转发头绝不能参与限流键计算。
- 多 worker 且无 Redis 时，各进程独立计数。

## 测试

`tests/middleware/test_rate_limit.py` 覆盖普通限流、严格认证限流、可信/不可信代理解析和 Redis 降级。
