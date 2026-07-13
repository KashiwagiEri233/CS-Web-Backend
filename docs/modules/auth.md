# 认证（Auth）

## 概述

登录、令牌签发/刷新、登出、注册与当前用户信息。  
**access + refresh 双令牌**；登出/改密后 access 经 `jti` 黑名单与 `pwd_at` 失效。  
负责身份认证，授权见 [rbac.md](rbac.md)。

代码：`app/api/v1/auth.py`、`app/services/auth_service.py`、`app/core/security.py`。  
挂载：`/api/v1/auth`。Service 经 `Depends(get_auth_service)` 注入。

## 接口

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/login` | 公开 | OAuth2 表单 → `TokenPair` |
| POST | `/login-json` | 公开 | JSON 登录 → `TokenPair` |
| POST | `/refresh` | 公开（持 refresh） | 轮换签发新 `TokenPair` |
| POST | `/logout` | 当前活跃用户 | 可选 body `RefreshRequest` + access 黑名单 |
| POST | `/register` | `user:create` | 创建用户 → `UserResponse`（写审计） |
| GET | `/me` | 当前活跃用户 | 当前用户 |

schema 见 `app/schemas/auth.py`。

## 配置

`SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEYS`、`JWT_ISSUER`、`JWT_AUDIENCE`、`JWT_ACCEPT_LEGACY_TOKENS`、`ALGORITHM`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`、`TOKEN_BLACKLIST_FALLBACK`、`REQUIRE_REDIS_FOR_SECURITY`、认证限流字段。

## 安全要点

- JWT 校验支持历史密钥轮换窗口。
- access 含微秒精度 `pwd_at`，与 `password_changed_at` 对比，避免同一秒改密时旧令牌继续有效。
- refresh 轮换会锁定当前令牌行；同一 refresh 的并发请求只有一个能正常换新，后续请求触发整条 family 撤销。
- 已撤销 refresh 保留到自然过期，保证重放检测；清理任务只删除过期记录。
- 密码按 UTF-8 编码后最多 72 字节，与 bcrypt 的输入边界一致。
- 软删用户不可登录/刷新。

## 测试

`tests/api/v1/test_auth.py`、`tests/services/test_auth_service.py`、`tests/integration/test_auth_token_lifecycle.py`、`tests/core/test_token_blacklist.py`。
