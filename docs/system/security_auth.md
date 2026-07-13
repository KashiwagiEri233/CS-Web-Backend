# 安全与鉴权基础设施

## 概述

本模块覆盖 PyJWT 签发与校验、密码哈希、access token 黑名单、当前用户解析以及 RBAC
权限依赖。业务 API 仍通过 `require_permission(resource, action)` 声明授权要求。

## 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `create_access_token` | `create_access_token(data) -> (token, jti, exp)` | 签发 access token |
| `verify_token` | `verify_token(token) -> dict | None` | 校验签名、issuer、audience 和 access token 类型 |
| `async_get_password_hash` | `await async_get_password_hash(password)` | 在线程池执行 bcrypt |
| `async_verify_password` | `await async_verify_password(raw, hashed)` | 在线程池校验 bcrypt |
| `get_current_user` | FastAPI dependency | 解析 token、用户及撤销状态 |
| `require_permission` | `require_permission(resource, action)` | 构造细粒度权限依赖 |

## 配置

关键配置包括 `SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEYS`、`JWT_ISSUER`、
`JWT_AUDIENCE`、`JWT_ACCEPT_LEGACY_TOKENS`、token 有效期、
`TOKEN_BLACKLIST_FALLBACK` 和 `REQUIRE_REDIS_FOR_SECURITY`。

## 降级与不变量

- 新 token 必须携带 `iss`、`aud`、`iat`、`jti` 和 `token_type`。
- 旧 token 兼容仅用于迁移窗口；新部署关闭 `JWT_ACCEPT_LEGACY_TOKENS`。
- 多 worker 且要求即时撤销一致性时，必须配置 Redis 并开启
  `REQUIRE_REDIS_FOR_SECURITY`。
- bcrypt 输入限制为 72 UTF-8 字节，哈希操作不得阻塞事件循环。
- inactive 用户和 inactive 角色都不能授予访问权限。

## 测试

- `tests/core/test_security.py`、`test_token_blacklist.py`。
- `tests/middleware/test_rbac_permissions.py`。
- `tests/integration/test_http_postgres_e2e.py`、`test_redis_backends.py`。

## 扩展指引

新增安全声明时，同时更新签发、校验和反向测试；新增权限必须登记 seed 数据并通过
`resource:action` 唯一约束。
