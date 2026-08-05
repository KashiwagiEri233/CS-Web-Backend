# 业务模块（Auth / Users / RBAC / Audit）

> 本文件合并了原 `modules/auth.md`、`modules/users.md`、`modules/rbac.md`、`modules/audit.md`，
> 统一阐述与具体业务实体绑定的四个核心模块。

---

## 一、认证（Auth）

### 概述

登录、令牌签发/刷新、登出、注册与当前用户信息。
**access + refresh 双令牌**；登出/改密后 access 经 `jti` 黑名单与 `pwd_at` 失效。
授权见「三、RBAC（角色 / 权限）」节与 `../AGENTS.md`。

代码：`app/api/v1/auth.py`、`app/services/auth_service.py`、`app/core/security.py`、
`app/services/totp_service.py`、`verification_service.py`、`oauth_service.py`、`password_reset_service.py`、
`app/core/totp.py`、`totp_encryption.py`、`password_compat.py`。挂载：`/api/v1/auth`。

### 接口

**基础认证**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/login` | 公开 | OAuth2 表单（用户名）→ `TokenPair` |
| POST | `/login-json` | 公开 | JSON 登录（用户名）→ `TokenPair` |
| POST | `/login-email` | 公开 | 邮箱登录（前端主路径）→ `LoginResponse`（2FA 感知） |
| POST | `/register` | 公开 | 注册（邮箱+密码+验证码）→ `LoginResponse`（自动登录） |
| POST | `/send-code` | 公开 | 发送邮箱验证码（已注册邮箱 409） |
| POST | `/forgot-password` | 公开 | 创建密码重置申请（防枚举） |
| POST | `/refresh` | 公开（持 refresh） | 轮换签发新 `TokenPair` |
| POST | `/logout` | 当前活跃用户 | 可选 body `RefreshRequest` + access 黑名单 |
| GET | `/me` | 当前活跃用户 | 用户 + 角色 + 2FA 状态（`MeResponse`） |

**2FA（TOTP）**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/2fa` | 当前活跃用户 | 状态查询（enabled / setup） |
| POST | `/2fa/setup` | 当前活跃用户 | 初始化：secret + otpauth URI + 备用码 |
| POST | `/2fa/verify` | 视 mode | `mode=setup` 确认启用；`mode=login` 预认证 token + 码完成登录 |
| POST | `/2fa/disable` | 当前活跃用户 | 禁用（需当前 TOTP/备用码） |
| POST | `/2fa/backup-codes` | 当前活跃用户 | 重新生成备用码 |

**OAuth**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/oauth/github` | 公开 | 302 跳转 GitHub；未配置返回 400 |
| GET | `/oauth/github/callback` | 公开 | 回调 → `LoginResponse`（2FA 感知） |

**会话管理**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/sessions` | 当前活跃用户 | 活跃 refresh token 列表（含 ip/user_agent） |
| DELETE | `/sessions/{token_id}` | 当前活跃用户 | 远程登出（须属于当前用户） |

### 配置

`SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEYS`、`JWT_ISSUER`、`JWT_AUDIENCE`、`JWT_ACCEPT_LEGACY_TOKENS`（默认 `False`）、
`ALGORITHM`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`、`REFRESH_TOKEN_ROTATION_LEEWAY_SECONDS`、
`TOKEN_BLACKLIST_FALLBACK`、`REQUIRE_REDIS_FOR_SECURITY`、认证限流字段。

Phase 1 新增（全部登记 `.env.example`）：

| 配置 | 说明 |
|---|---|
| `TOTP_ENCRYPTION_KEY` | 2FA secret 加密主密钥（≥32 字节，必填，fail-fast） |
| `TOTP_ISSUER` / `TOTP_STEP_SECONDS` / `TOTP_WINDOW_STEPS` / `TOTP_PRE_AUTH_TTL_MINUTES` | TOTP 参数与预认证 token 有效期 |
| `VERIFICATION_CODE_TTL_MINUTES` | 邮箱验证码有效期（默认 10） |
| `PASSWORD_HISTORY_LIMIT` | 历史密码复用检测条数（默认 5；0=禁用） |
| `PASSWORD_RESET_DEFAULT` | 管理员批准重置的默认密码（未配置时审批接口拒绝） |
| `SMTP_HOST/PORT/SECURE/USER/PASS/FROM/TLS_SKIP_VERIFY` | 邮件；HOST 为空回退控制台 |
| `GITHUB_CLIENT_ID/SECRET/CALLBACK_URL` | GitHub OAuth；未配置时入口 400 |
| `SITE_URL` | BFF 站点地址，用于默认 OAuth 回调 URL |

### 安全要点

- JWT 校验支持历史密钥轮换窗口。
- access 含微秒精度 `pwd_at`，与 `password_changed_at` 对比。
- refresh 轮换锁定当前行；已撤销 token 在宽限窗口内重用视为并发重试；超窗/family 无活跃 token 才吊销整条 family。
- 密码按 UTF-8 编码后最多 72 字节。
- 软删用户不可登录/刷新。
- 登录成功/失败均写审计（best-effort）。
- **邮箱登录**：不区分"用户不存在/密码错误"（防枚举）；dummy bcrypt 均衡时序；账号级限流。
- **密码迁移（OQ-5 懒升级）**：scrypt 旧哈希验证通过后自动重哈希为 bcrypt；备用码同理兼容两种哈希。
- **TOTP**：RFC 6238（SHA1/6 位/30s/±1 窗口）；secret 加密存储；预认证 token 一次性消费防重放。
- **GitHub OAuth**：state 一次性 + 10 分钟过期；邮箱已注册但未绑定不自动绑定（防账号接管）。
- **改密/重置**：同事务撤销全部 refresh + `pwd_at`；SELF_APPROVE 禁止管理员批准自己的重置。

### 测试

`tests/api/v1/test_auth.py`、`tests/services/test_auth_service.py`、`tests/integration/test_auth_token_lifecycle.py`、
`test_auth_phase1.py`（需 PG）、`tests/core/test_totp.py`、`test_totp_encryption.py`、`test_password_compat.py`、`test_token_blacklist.py`。

---

## 二、用户管理（Users）

### 概述

用户 CRUD、自助资料与公开主页。软删除（`deleted_at`）；改密与撤 refresh **同一事务**。

代码：`app/api/v1/users.py`、`app/api/v1/profile.py`、`app/services/user_service.py`。前缀：`/api/v1/users`、`/profile`、`/avatars`。

### 接口

**用户管理**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/users` | `user:list` | 分页列表（不含已软删） |
| GET | `/users/me` | 活跃用户 | 当前用户 |
| GET | `/users/{user_id}` | `user:read` | 详情 |
| POST | `/users` | `user:create` | 创建 + 审计 |
| PUT | `/users/{user_id}` | `user:update` | 更新；改密同事务撤 refresh + 审计 |
| PUT | `/users/me` | 活跃用户 | 自助（不可改 is_active；改密需 `old_password`） |
| DELETE | `/users/{user_id}` | `user:delete` | 软删 + 撤 refresh + 审计（禁自删） |

**个人资料（前端主路径）**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/profile` | 活跃用户 | 完整资料 + 活动参与记录（`ProfileResponse`） |
| PUT | `/profile` | 活跃用户 | 更新 displayName/bio/githubUrl/websiteUrl/techTags |
| POST | `/profile/password` | 活跃用户 | 改密（旧密码 + 历史复用检测 + 全端登出） |
| POST | `/profile/avatar/preset` | 活跃用户 | 预设头像（preset_id 1-6） |
| POST | `/profile/avatar/upload` | 活跃用户 | 上传头像（≤2MB，JPEG/PNG/WebP/GIF，魔数校验） |
| GET | `/avatars/{filename}` | 公开 | 头像静态服务（文件名严格校验防路径遍历） |
| GET | `/users/{user_id}` | 公开 | 用户公开主页 + 论坛/考试统计 |

### 安全

- 改密：`password_changed_at` + 微秒 JWT `pwd_at`；同事务 `revoke_all_for_user`。
- 自助改密必须校验旧密码，防 access 泄露被接管；管理端重置不需要。
- 密码 ≤72 UTF-8 字节，避免 bcrypt 静默截断。
- 软删释放 username/email 唯一键（截断拼接后缀）。
- 头像四重校验（大小/MIME 白名单/扩展名白名单/文件头魔数）；文件名服务端生成。
- 公开主页仅返回已激活未软删用户。

### 测试

`tests/api/v1/test_users.py`、`tests/services/test_user_service.py`、`tests/integration/test_auth_phase1.py`。

---

## 三、RBAC（角色 / 权限）

### 概述

角色、权限 CRUD，用户↔角色 / 角色↔权限分配，权限查询。管理端点用 `require_permission`；写操作写审计。

代码：`app/api/v1/rbac/`、`app/services/rbac_service.py`、`app/middleware/rbac.py`。前缀：`/api/v1/rbac`。

### 接口

**角色**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/roles` | `role:list` | 分页 `PaginatedResponse[Role]` |
| POST | `/roles` | `role:create` | 创建 + 审计 |
| GET | `/roles/{role_id}` | `role:read` | 详情 |
| PUT | `/roles/{role_id}` | `role:update` | 更新 + 审计 |
| DELETE | `/roles/{role_id}` | `role:delete` | 删除 + 审计 |

**权限**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/permissions` | `permission:list` | 分页 |
| POST | `/permissions` | `permission:create` | 创建 + 审计 |
| GET | `/permissions/{permission_id}` | `permission:read` | 详情 |
| PUT | `/permissions/{permission_id}` | `permission:update` | 更新 + 审计 |
| DELETE | `/permissions/{permission_id}` | `permission:delete` | 删除 + 审计 |

**分配与查询**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST/DELETE | `/users/{uid}/roles/{rid}` | `user:manage_roles` | 赋/撤角色 + 审计；目标为 admin 角色或超级用户时需操作者是超级用户 |
| POST/DELETE | `/roles/{rid}/permissions/{pid}` | `role:manage_permissions` | 赋/撤权限 + 审计 |
| POST | `/users/{uid}/check-permission` | 活跃用户（本人/超管） | 校验 |
| GET | `/me/permissions` · `/me/roles` | 活跃用户 | 当前授权 |
| GET | `/users/{uid}/permissions` · `/roles` | `user:read` | 指定用户 |

### 缓存

用户权限缓存键 `rbac:user_perms:{user_id}`，TTL 60s；grant/revoke 与角色/权限 CRUD 失效。
缓存只用于展示/查询；实际授权每次直接查 DB。停用角色不授予身份或权限。

### 测试

`tests/api/v1/test_rbac.py`、`tests/services/test_rbac_service.py`、`tests/middleware/test_rbac_permissions.py`。

---

## 四、审计日志（Audit）

### 概述

记录敏感管理操作（谁、何时、对什么资源做了什么）。普通辅助写入用 **best-effort** 独立会话；
用户、角色、权限等敏感写用共享请求会话并严格提交，使业务变更与审计同事务。查询走请求级 `AsyncSession`。

代码：`app/api/v1/audit.py`、`app/services/audit_service.py`、`app/models/audit_log.py`、`app/schemas/audit.py`。前缀：`/api/v1/audit`。

### 接口

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/logs` | `system:logs` | 分页列表 → `PaginatedResponse[AuditLogItem]` |
| GET | `/logs/{log_id}` | `system:logs` | 详情 → `AuditLogItem` |
| DELETE | `/logs/{log_id}` | `root` | 删除单条审计日志 |
| DELETE | `/logs?before=<datetime>` | `root` | 批量删除指定时间之前的审计日志 |

查询参数（列表）：`skip` / `limit` / `action` / `resource_type` / `resource_id` / `actor_id` / `start_date` / `end_date`。

### 当前写入点

| action | 触发 |
|---|---|
| `user.create` | `POST /users`、`POST /auth/register` |
| `user.update` | `PUT /users/{id}` |
| `user.delete` | `DELETE /users/{id}` |
| `role.create/update/delete` | RBAC 角色写操作 |
| `permission.create/update/delete` | RBAC 权限写操作 |
| `user.grant_role` / `user.revoke_role` | 用户↔角色 |
| `role.grant_permission` / `role.revoke_permission` | 角色↔权限 |

### 配置 / 不变量

- 表：`audit_logs`（Alembic 迁移 `b8d4f02c3e15`）；权限种子 `system:logs`。
- 敏感写统一调 `record_atomic()`：共享会话、严格失败、一次提交；审计失败回滚业务事务；路由不得自行组合三个布尔开关。
- 非关键辅助审计默认 best-effort，失败只打 warning。
- 查询需 `system:logs`；超级用户旁路 `require_permission`。

### 测试

`tests/api/v1/test_audit.py`。
