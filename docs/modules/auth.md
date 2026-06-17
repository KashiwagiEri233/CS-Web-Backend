# 认证（Auth）

## 概述

负责登录、令牌签发/刷新、登出（令牌失效）、注册与当前用户信息。采用 **access + refresh 双令牌**：
access 短期（默认 15 分钟）、refresh 长期（默认 7 天）；登出/改密后通过 access token 黑名单
（`jti`）即时失效。负责"身份认证"，**不负责**"权限授权"（那是 RBAC，见 [rbac.md](rbac.md)）。

代码：`app/api/v1/auth.py`、`app/services/auth_service.py`、令牌原语 `app/core/security.py`。
挂载前缀：`/api/v1/auth`，tag `认证`。

## 接口

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/login` | 公开 | OAuth2 表单（`username`/`password`）→ `TokenPair` |
| POST | `/login-json` | 公开 | JSON body 登录 → `TokenPair` |
| POST | `/refresh` | 公开（持 refresh token） | 用 refresh token 换发新 `TokenPair` |
| POST | `/logout` | 当前活跃用户 | 将当前 access token 加入黑名单 |
| POST | `/register` | **超级用户** | 创建新用户 → `UserResponse` |
| GET | `/me` | 当前活跃用户 | 返回当前用户 → `UserResponse` |

入/出参 schema 见 `app/schemas/`（`TokenPair`、`UserResponse` 等）。

> 注意：`/register` 需超级用户，**不是**开放注册——这是后台管理型脚手架的默认姿态。
> 若要做公开注册，新增一个不带 `get_current_superuser` 依赖的端点，并配合限流。

## 配置

`app/core/config.py`：`ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`、`ALGORITHM`、
`SECRET_KEY`（必填，无默认）、`TOKEN_BLACKLIST_FALLBACK`（Redis 不可用时 `memory`/`open`）。
认证端点限流：`AUTH_RATE_LIMIT_CALLS` / `AUTH_RATE_LIMIT_PERIOD`（独立于全局限流，更严）。

## 依赖与协作

- 依赖原语：`app/core/security.py`（密码哈希 bcrypt、JWT 编解码、refresh token 生成/sha256 存储）。
- 鉴权依赖：`app/dependencies.py` 的 `get_current_active_user` / `get_current_superuser`。
- 黑名单：`app/core/`（Redis 可降级到内存）。

## 降级与不变量

- `AUTH_ENABLED=False` 时全局放行（仅 DEBUG，生产拒启）——此时认证端点形同虚设。
- access token 必须短期 + refresh 配合；不要把 access 过期时间拉长替代 refresh。
- 401 响应带 `WWW-Authenticate: Bearer`（OAuth2 规范，由异常体系保证）。

## 测试

`tests/integration/test_auth_token_lifecycle.py`（登录→刷新→登出黑名单全流程）、
`tests/core/test_token_blacklist.py`、`tests/core/test_auth_toggle.py`（`AUTH_ENABLED` 开关）。

## 扩展指引

加认证相关端点：放 `app/api/v1/auth.py`，业务逻辑下沉到 `auth_service.py`（不依赖 `Request`）。
新增令牌类字段记得同步 `TokenPair` schema 与 `security.py` 的编解码。
