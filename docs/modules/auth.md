# 认证（Auth）

## 概述

登录、令牌签发/刷新、登出、注册与当前用户信息。  
**access + refresh 双令牌**；登出/改密后 access 经 `jti` 黑名单与 `pwd_at` 失效。  
负责身份认证，授权见 [rbac.md](rbac.md)。

代码：`app/api/v1/auth.py`、`app/services/auth_service.py`、`app/core/security.py`、
`app/services/totp_service.py`、`app/services/verification_service.py`、
`app/services/oauth_service.py`、`app/services/password_reset_service.py`、
`app/core/totp.py`、`app/core/totp_encryption.py`、`app/core/password_compat.py`。  
挂载：`/api/v1/auth`。Service 经 `Depends(get_auth_service)` 注入。

> Phase 1（前后端分离迁移）新增能力：邮箱登录、公开注册（验证码）、TOTP 2FA、
> GitHub OAuth、忘记密码申请流、邮箱验证码、登录历史、设备列表/远程登出、
> scrypt→bcrypt 懒升级。

## 接口

### 基础认证

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/login` | 公开 | OAuth2 表单（用户名）→ `TokenPair` |
| POST | `/login-json` | 公开 | JSON 登录（用户名）→ `TokenPair` |
| POST | `/login-email` | 公开 | 邮箱登录（前端主路径）→ `LoginResponse`（2FA 感知） |
| POST | `/register` | 公开 | 注册（邮箱+密码+验证码）→ `LoginResponse`（自动登录） |
| POST | `/send-code` | 公开 | 发送邮箱验证码（已注册邮箱 409） |
| POST | `/forgot-password` | 公开 | 创建密码重置申请（防枚举，统一成功消息） |
| POST | `/refresh` | 公开（持 refresh） | 轮换签发新 `TokenPair` |
| POST | `/logout` | 当前活跃用户 | 可选 body `RefreshRequest` + access 黑名单 |
| GET | `/me` | 当前活跃用户 | 用户 + 角色 + 2FA 状态（`MeResponse`） |

### 2FA（TOTP）

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/2fa` | 当前活跃用户 | 状态查询（enabled / setup） |
| POST | `/2fa/setup` | 当前活跃用户 | 初始化：secret + otpauth URI + 备用码（未启用） |
| POST | `/2fa/verify` | 视 mode | `mode=setup` 确认启用；`mode=login` 预认证 token + 码完成登录 |
| POST | `/2fa/disable` | 当前活跃用户 | 禁用（需当前 TOTP/备用码） |
| POST | `/2fa/backup-codes` | 当前活跃用户 | 重新生成备用码（需当前 TOTP/备用码） |

### OAuth

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/oauth/github` | 公开 | 302 跳转 GitHub；未配置返回 400 |
| GET | `/oauth/github/callback` | 公开 | 回调 → `LoginResponse`（2FA 感知） |

### 会话管理（设备列表 / 远程登出）

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/sessions` | 当前活跃用户 | 活跃 refresh token 列表（含 ip/user_agent） |
| DELETE | `/sessions/{token_id}` | 当前活跃用户 | 远程登出（须属于当前用户） |

schema 见 `app/schemas/auth.py`。2FA 加密见 `app/core/totp_encryption.py`（与前端
HKDF-SHA256 + AES-256-GCM 算法逐字节兼容，迁移期可直接解密旧密文）。

## 配置

`SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEYS`、`JWT_ISSUER`、`JWT_AUDIENCE`、`JWT_ACCEPT_LEGACY_TOKENS`（默认 `False`）、`ALGORITHM`、`ACCESS_TOKEN_EXPIRE_MINUTES`、
`REFRESH_TOKEN_EXPIRE_DAYS`、`REFRESH_TOKEN_ROTATION_LEEWAY_SECONDS`、`TOKEN_BLACKLIST_FALLBACK`、`REQUIRE_REDIS_FOR_SECURITY`、认证限流字段。

Phase 1 新增（全部登记于 `.env.example`）：

| 配置 | 说明 |
|---|---|
| `TOTP_ENCRYPTION_KEY` | 2FA secret 加密主密钥（≥32 字节，必填，fail-fast） |
| `TOTP_ISSUER` / `TOTP_STEP_SECONDS` / `TOTP_WINDOW_STEPS` / `TOTP_PRE_AUTH_TTL_MINUTES` | TOTP 参数与预认证 token 有效期 |
| `VERIFICATION_CODE_TTL_MINUTES` | 邮箱验证码有效期（默认 10） |
| `PASSWORD_HISTORY_LIMIT` | 历史密码复用检测条数（默认 5；0=禁用） |
| `PASSWORD_RESET_DEFAULT` | 管理员批准重置的默认密码（未配置时审批接口拒绝执行） |
| `SMTP_HOST/PORT/SECURE/USER/PASS/FROM/TLS_SKIP_VERIFY` | 邮件；HOST 为空回退控制台输出 |
| `GITHUB_CLIENT_ID/SECRET/CALLBACK_URL` | GitHub OAuth；未配置时入口 400 |
| `SITE_URL` | BFF 站点地址，用于默认 OAuth 回调 URL |

## 安全要点

- JWT 校验支持历史密钥轮换窗口。
- access 含微秒精度 `pwd_at`，与 `password_changed_at` 对比，避免同一秒改密时旧令牌继续有效。
- refresh 轮换会锁定当前令牌行；已撤销 token 在宽限窗口（`REFRESH_TOKEN_ROTATION_LEEWAY_SECONDS`，默认 10s）内重用视为并发重试放行；超出窗口、或 family 已无活跃 token（整体撤销）时才吊销整条 family。
- 已撤销 refresh 保留到自然过期，保证重放检测；清理任务只删除过期记录。
- 密码按 UTF-8 编码后最多 72 字节，与 bcrypt 的输入边界一致。
- 软删用户不可登录/刷新。
- 登录成功（`auth.login`）与失败（`auth.login_failed`）均写审计（best-effort，不阻断登录）。
- **邮箱登录**：不区分"用户不存在/密码错误"（防枚举）；用户不存在时执行 dummy bcrypt 均衡时序；账号级限流（按邮箱）。
- **密码迁移（OQ-5 懒升级）**：scrypt 旧哈希（前端格式 `saltHex:hashHex`）验证通过后自动重哈希为 bcrypt（见 `app/core/password_compat.py`）；备用码同理兼容两种哈希。
- **TOTP**：RFC 6238（SHA1/6 位/30s/±1 窗口）；secret 加密存储；预认证 token（scope=2fa，短 TTL）经黑名单一次性消费防重放；备用码一次性。
- **GitHub OAuth**：state 一次性 + 10 分钟过期；邮箱已注册但未绑定 → 不自动绑定（`GITHUB_EMAIL_CONFLICT`，防账号接管）。
- **改密/重置**：同事务撤销全部 refresh + `pwd_at` 使旧 access 失效；SELF_APPROVE 禁止管理员批准自己的重置申请。

## 测试

`tests/api/v1/test_auth.py`、`tests/services/test_auth_service.py`、`tests/integration/test_auth_token_lifecycle.py`、
`tests/integration/test_auth_phase1.py`（Phase 1 全流程，需 PG）、`tests/core/test_totp.py`、
`tests/core/test_totp_encryption.py`（含 Node 交叉验证向量）、`tests/core/test_password_compat.py`、
`tests/core/test_token_blacklist.py`。
