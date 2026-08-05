# 安全与防护（鉴权 / 异常 / 限流）（BackDoc-Sec）

> 更新人：3yearsZ
> 最后更新：2026-08-05（统一 BackDoc 命名）
> 关联：架构见 [BackDoc-Arch.md](BackDoc-Arch.md)；基础设施见 [BackDoc-Infra.md](BackDoc-Infra.md)；编码规范见 [BackDoc-Conv.md](BackDoc-Conv.md)
> 本文件合并了原 `system/security_auth.md`、`system/exception_handling.md`、`system/rate_limit.md`，
> 统一阐述"请求如何被安全地鉴权、异常如何被规范化处理、过量流量如何被限流"。

---

## 一、鉴权与安全基础设施

### 概述

覆盖 PyJWT 签发与校验、密码哈希、access token 黑名单、当前用户解析以及 RBAC
权限依赖。业务 API 仍通过 `require_permission(resource, action)` 声明授权要求。

代码：`app/core/security.py`、`app/core/security_blacklist.py`、`app/middleware/rbac.py`、`app/core/password_compat.py`。

### 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `create_access_token` | `create_access_token(data) -> (token, jti, exp)` | 签发 access token |
| `verify_token` | `verify_token(token) -> dict \| None` | 校验签名、issuer、audience 和 access token 类型 |
| `async_get_password_hash` | `await async_get_password_hash(password)` | 在线程池执行 bcrypt |
| `async_verify_password` | `await async_verify_password(raw, hashed)` | 在线程池校验 bcrypt |
| `get_current_user` | FastAPI dependency | 解析 token、用户及撤销状态 |
| `require_permission` | `require_permission(resource, action)` | 构造细粒度权限依赖 |

### 配置

关键配置：`SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEYS`、`JWT_ISSUER`、`JWT_AUDIENCE`、
`JWT_ACCEPT_LEGACY_TOKENS`、token 有效期、`TOKEN_BLACKLIST_FALLBACK`、`REQUIRE_REDIS_FOR_SECURITY`。

### 降级与不变量

- 新 token 必须携带 `iss`、`aud`、`iat`、`jti` 和 `token_type`。
- 旧 token 兼容仅用于迁移窗口；`JWT_ACCEPT_LEGACY_TOKENS` 默认关闭。所有 token 强制 `exp`（缺失即拒绝）。
- 黑名单 Redis 恢复后仍回查进程内存，覆盖降级窗口内本进程拉黑的 jti（`fallback="open"` 除外）。
- 多 worker 且要求即时撤销一致性时，必须配置 Redis 并开启 `REQUIRE_REDIS_FOR_SECURITY`：校验期强制 `REDIS_URL`、强制 `TOKEN_BLACKLIST_FALLBACK=closed`、Redis 不可用时启动拒绝（fail-closed）。
- bcrypt 输入限制为 72 UTF-8 字节；哈希不得阻塞事件循环。
- inactive 用户和 inactive 角色都不能授予访问权限。

### 测试

`tests/core/test_security.py`、`test_token_blacklist.py`、`tests/middleware/test_rbac_permissions.py`、
`tests/integration/test_http_postgres_e2e.py`、`test_redis_backends.py`。

### 扩展指引

新增安全声明时同时更新签发、校验和反向测试；新增权限必须登记 seed 数据并通过 `resource:action` 唯一约束。

---

## 二、异常处理

### 概述

用 `BaseAppException` 子类表达业务失败，由全局处理器转换为统一错误响应；未处理异常由最外层异常中间件兜底。
错误码集中在 `ErrorCode` 注册表，异常日志异步持久化，避免路由自行拼装错误 JSON。

代码：`app/core/exceptions/`、`app/models/exception_log.py`、`app/repositories/exception_log_repo.py`。

### 接口

| 符号 | 用途 |
|---|---|
| `BaseAppException` | 业务异常基类，承载状态码、错误码、消息和安全详情 |
| `ErrorCode` | 客户端错误码的单一事实源 |
| `setup_exception_handlers(app)` | 注册业务异常、FastAPI 校验、HTTP、数据库和兜底处理器 |
| `ExceptionHandlerMiddleware` | 捕获路由层外异常并按状态映射统一响应 |

异常日志查询接口挂载于 `/api/v1/exceptions`（仅供超级用户），契约以 `app/api/v1/exceptions.py` 与 `app/schemas/exception_log.py` 为准。

### 响应与安全

统一错误响应包含 `success=false`、`error_code`、`message`、`status_code`、`timestamp`，按异常类型可带安全 `details`。

- Pydantic 校验错误移除原始 `input`，避免密码、令牌回显或落日志。
- 数据库异常只返回稳定错误码和通用消息，不返回驱动异常/SQL/约束原文。
- 日志记录请求路径，不记录带查询参数的完整 URL。
- 业务异常必须引用 `ErrorCode.*`，禁止裸字符串错误码。
- 中间件短路用 `JSONResponse`，不抛 `HTTPException`。

### 持久化与降级

异常日志通过独立数据库会话写入，失败只写应用日志，不覆盖原始 HTTP 响应。表结构由 Alembic 维护；应用代码和测试不得调用 `create_all`。

### 扩展指引

1. 在 `base_exceptions.py` 定义或复用异常类。
2. 在 `error_codes.py` 对应命名空间登记错误码。
3. 从 `app/core/exceptions/__init__.py` 导出公共异常。
4. 仅需专属转换逻辑时才在 `setup_exception_handlers` 注册处理器。
5. 补充 handler、middleware 和 service 层测试。

### 测试

`tests/core/test_exception_handlers.py`、`test_exception_handler_middleware.py`、`test_exception_logging.py`、`tests/services/test_exception_service.py`。

---

## 三、请求限流

### 概述

限流后端优先 Redis（多实例共享计数），未配置或故障时降级为进程内存。
全局限流覆盖所有请求，认证限流额外覆盖登录、注册和 refresh 端点。

代码：`app/core/rate_limit/`、`app/middleware/rate_limit.py`；客户端 IP 解析见 `app/core/request_context.py`。

### 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_client_ip` | `get_client_ip(request, trusted_proxies=()) -> str` | 从可信代理链解析真实客户端 IP |
| `RateLimitMiddleware` | `RateLimitMiddleware(app, calls, period, limit_paths=None)` | 全局或指定路径限流 |
| `AuthRateLimitMiddleware` | `AuthRateLimitMiddleware(app, calls, period)` | 认证端点严格限流 |

超限返回统一 `429` JSON 和 `Retry-After`，中间件不抛 `HTTPException`。

### 配置

- `RATE_LIMIT_CALLS` / `RATE_LIMIT_PERIOD`：全局窗口。
- `AUTH_RATE_LIMIT_CALLS` / `AUTH_RATE_LIMIT_PERIOD`：认证窗口。
- `TRUSTED_PROXY_CIDRS`：可信反向代理 CIDR；为空忽略 `X-Forwarded-For`/`X-Real-IP`。
- `REDIS_URL` 及 Redis 超时/重试配置：控制共享后端和故障降级。

只有直连来源处于可信网段时才读取转发头，并从右向左跳过可信代理，取第一个不可信地址。部署在反向代理后应填写实际代理网段，不用过宽公网网段。

### 降级与不变量

- Redis 是增强项，不是启动依赖；故障后限流退化为单进程语义。
- 不可信来源的转发头绝不参与限流键计算。
- 多 worker 且无 Redis 时各进程独立计数。

### 测试

`tests/middleware/test_rate_limit.py`：普通限流、严格认证限流、可信/不可信代理解析、Redis 降级。
