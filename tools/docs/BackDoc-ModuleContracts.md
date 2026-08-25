# BackDoc-ModuleContracts：后端业务模块契约（Reference · 回答「是什么」，提供 7 个模块的接口、配置、不变量的精确权威定义）

> 更新人：3yearsZ
> 更新日：2026-08-20
> 版本：1.0.1 · 七夕（Diátaxis R 类规范，模块 SSOT 权威）
> Diátaxis：R（Reference · 回答「是什么」，提供业务模块的接口契约、配置项、不变量的权威定义；不包含可执行步骤）
> 适用读者：后端开发者 / 前端 BFF 对接者 / 接口联调测试者；已了解后端架构
> 变更触发：路由表变更 / 新增模块 / 配置项调整 / 不变量变更

> **SSOT 分工声明**：
> - 本文档是「**后端 7 个业务模块的接口契约、配置项、不变量**」的唯一权威（SSOT）。
> - 基础设施契约（日志/数据库/缓存/队列）→ [BackDoc-Infra.md](BackDoc-Infra.md)（Reference）。
> - 安全约束（鉴权/限流/密钥）→ [BackDoc-02-Sec.md](BackDoc-02-Sec.md)。
> - 工程约定（分层/命名/代码规范）→ [BackDoc-03-Conv.md](BackDoc-03-Conv.md)。
> - 架构总览（模块依赖、运行时序列）→ [BackDoc-01-Arch.md](BackDoc-01-Arch.md)（Arc42）。
> - 完整 OpenAPI 契约（method/path/schema）→ 根仓 `openapi.baseline.json`。

> **治理红线**：
> - MUST NOT 在本文档重抄字段 schema；字段约束以 `app/schemas/` 和 `openapi.baseline.json` 为准
> - MUST 在新增/修改路由时同步更新本文档的接口契约表
> - MUST 在新增/修改配置项时同步更新本文档的配置项表
> - MUST 在新增/修改业务约束时同步更新本文档的不变量表（RFC 2119 关键词）
> - 完整契约（method / path / requestBody / responses / schemas）以根仓 `openapi.baseline.json` 为准；字段约束以代码 `app/schemas/` 为准

> **文档结构**：本文档按「模块」组织，每个模块独立成节。每节包含：
> 1. **概述**：模块职责、路由前缀、代码位置
> 2. **接口契约**：路由 method/path/鉴权/说明
> 3. **配置项与不变量**：环境变量、RFC 2119 约束
> 4. **测试覆盖**：单元/集成测试文件路径

---

## 快速索引

| 模块 | 概述 | 接口契约 | 配置项与不变量 | 测试覆盖 | 代码位置 |
|---|---|---|---|---|---|
| **§1 认证（Auth）** | 登录/令牌/注册/2FA/OAuth | §1.2 | §1.3 | §1.4 | `app/api/v1/auth.py`、`app/services/auth_service.py` |
| **§2 用户管理（Users）** | CRUD/自助资料/公开主页 | §2.2 | §2.3 | §2.4 | `app/api/v1/users.py`、`app/services/user_service.py` |
| **§3 RBAC（角色/权限）** | 角色权限 CRUD/分配 | §3.2 | §3.3 | §3.4 | `app/api/v1/rbac/`、`app/middleware/rbac.py` |
| **§4 审计日志（Audit）** | 敏感操作审计记录 | §4.2 | §4.3 | §4.4 | `app/api/v1/audit.py`、`app/services/audit_service.py` |
| **§5 工作台（Workbench）** | 个人效率/学习数据聚合 | §5.2 | §5.3 | §5.4 | `app/api/v1/workbench.py`、`app/services/contribution_service.py` |
| **§6 学习助手（Auxilio）** | LLM 对话/工具调用/Trajectory | §6.2 | §6.3 | §6.4 | `app/api/v1/auxilio.py`、`app/services/auxilio_agent.py` |
| **§7 API 调用统计（Middleware）** | 纯 ASGI 埋点 | §7.2 | §7.3 | §7.4 | `app/middleware/api_usage.py` |

---

## §1 认证（Auth）

### 1.1 概述

登录、令牌签发/刷新、登出、注册与当前用户信息。架构：access + refresh 双令牌；登出/改密后 access 经 `jti` 黑名单与 `pwd_at` 失效。

| 属性 | 值 |
|------|----|
| 挂载前缀 | `/api/v1/auth` |
| 代码位置 | `app/api/v1/auth.py`、`app/services/auth_service.py`、`app/core/security.py`、`app/services/totp_service.py`、`verification_service.py`、`oauth_service.py`、`password_reset_service.py` |

### 1.2 接口契约

#### 1.2.1 基础认证
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| POST | `/login` | 公开 | OAuth2 表单（用户名）→ `TokenPair` |
| POST | `/login-json` | 公开 | JSON 登录（用户名）→ `TokenPair` |
| POST | `/login-email` | 公开 | 邮箱登录（前端主路径）→ `LoginResponse`（2FA 感知） |
| POST | `/register` | 公开 | 注册（邮箱+密码+验证码）→ `LoginResponse`（自动登录） |
| POST | `/send-code` | 公开 | 发送邮箱验证码（已注册邮箱 → 409） |
| POST | `/forgot-password` | 公开 | 创建密码重置申请（防枚举） |
| POST | `/refresh` | 公开（持 refresh） | 轮换签发新 `TokenPair` |
| POST | `/logout` | 当前活跃用户 | 可选 body `RefreshRequest` + access 黑名单 |
| GET | `/me` | 当前活跃用户 | 用户 + 角色 + 2FA 状态（`MeResponse`） |

#### 1.2.2 2FA（TOTP）
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| GET | `/2fa` | 当前活跃用户 | 状态查询（enabled / setup） |
| POST | `/2fa/setup` | 当前活跃用户 | 初始化：secret + otpauth URI + 备用码 |
| POST | `/2fa/verify` | 视 mode | `mode=setup` 确认启用；`mode=login` 预认证 token + 码完成登录 |
| POST | `/2fa/disable` | 当前活跃用户 | 禁用（需当前 TOTP / 备用码） |
| POST | `/2fa/backup-codes` | 当前活跃用户 | 重新生成备用码 |

#### 1.2.3 OAuth
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| GET | `/oauth/github` | 公开 | 302 跳转 GitHub；未配置 → 400 |
| GET | `/oauth/github/callback` | 公开 | 回调 → `LoginResponse`（2FA 感知） |

#### 1.2.4 会话管理
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| GET | `/sessions` | 当前活跃用户 | 活跃 refresh token 列表（含 ip / user_agent） |
| DELETE | `/sessions/{token_id}` | 当前活跃用户 | 远程登出（token **MUST** 属于当前用户） |

### 1.3 配置项与不变量

#### 1.3.1 配置项表（登记 `.env.example`）
| 配置 | 说明 | RFC 2119 要求 |
|------|------|--------------|
| `SECRET_KEY` | JWT 签发主密钥 | **MUST** ≥32 字节；生产 **MUST NOT** 使用默认值 |
| `JWT_PREVIOUS_SECRET_KEYS` | 历史密钥轮换（逗号分隔） | **MAY** 留空 |
| `JWT_ISSUER` / `JWT_AUDIENCE` | iss / aud 声明 | **SHOULD** 设置 |
| `JWT_ACCEPT_LEGACY_TOKENS` | 是否接受旧版（非 family）token | 默认 `False`；迁移期 **MAY** 临时开 True |
| `ALGORITHM` | JWT 签名算法 | **MUST NOT** 使用 HS256 以下；默认 HS256（对称） |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | access 有效期 | 默认 15；生产 **SHOULD NOT** >30 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | refresh 有效期 | 默认 7 |
| `REFRESH_TOKEN_ROTATION_LEEWAY_SECONDS` | 轮换重试宽限窗口 | 默认 10 |
| `TOKEN_BLACKLIST_FALLBACK` | Redis 不可用时黑名单降级策略 | **SHOULD** `memory`；无状态部署设 `reject` |
| `REQUIRE_REDIS_FOR_SECURITY` | 强制 Redis 作黑名单 / 限流层 | 默认 False；单节点 **SHOULD NOT** True |
| `TOTP_ENCRYPTION_KEY` | 2FA secret AES-GCM 加密主密钥 | **MUST** ≥32 字节；缺则启动 fail-fast |
| `TOTP_ISSUER` | TOTP 发行者（展示在 Authenticator App） | **SHOULD** 设置为品牌名 |
| `TOTP_STEP_SECONDS` | TOTP 步长 | 默认 30；**MUST NOT** ≠ RFC 6238 默认值（兼容 App） |
| `TOTP_WINDOW_STEPS` | TOTP 容忍窗口（步为单位） | 默认 1（±30s）；高安全场景 **MAY** 0 |
| `TOTP_PRE_AUTH_TTL_MINUTES` | 2FA 预认证 token 有效期 | 默认 5 |
| `VERIFICATION_CODE_TTL_MINUTES` | 邮箱验证码有效期 | 默认 10 |
| `PASSWORD_HISTORY_LIMIT` | 历史密码复用检测条数 | 默认 5；0 = 禁用 |
| `PASSWORD_RESET_DEFAULT` | 管理员批准重置的默认密码 | 未配置时审批接口 **MUST** 拒绝 |
| `SMTP_HOST/PORT/SECURE/USER/PASS/FROM/TLS_SKIP_VERIFY` | 邮件服务器 | HOST 为空 **MUST** 回退控制台打印，**MUST NOT** 抛错 |
| `GITHUB_CLIENT_ID/SECRET/CALLBACK_URL` | GitHub OAuth | 未配置时入口 **MUST** 返回 400，**MUST NOT** 5xx |
| `SITE_URL` | BFF 站点地址（默认 OAuth 回调拼接） | **SHOULD** 设置 |

#### 1.3.2 不变量与约束（RFC 2119）
| 等级 | 约束 |
|---|---|
| **MUST** | 支持 JWT 历史密钥轮换窗口（`JWT_PREVIOUS_SECRET_KEYS`） |
| **MUST** | 在 access 内携带微秒精度 `pwd_at`，登录时对比 `password_changed_at` |
| **MUST** | refresh 轮换 **MUST** 行锁当前 token；已撤销 token 在宽限窗口内重用视为并发重试 |
| **MUST** | 密码 UTF-8 编码后 **MUST NOT** >72 字节（bcrypt 静默截断上限） |
| **MUST NOT** | 软删用户 **MUST NOT** 登录或刷新 |
| **MUST** | 登录成功 / 失败 **MUST** best-effort 写入审计 |
| **MUST** | 邮箱登录 **MUST** 不区分「用户不存在 / 密码错误」，统一相同延迟与响应（防枚举） |
| **SHOULD** | 密码迁移（scrypt 旧哈希）：验证通过后 **SHOULD** 自动重哈希为 bcrypt |
| **MUST** | TOTP **MUST** 按 RFC 6238（SHA1 / 6 位 / 30s / ±1 窗口）；secret **MUST** AES-GCM 加密存储 |
| **MUST NOT** | GitHub OAuth state **MUST** 一次性 + 10 分钟过期；邮箱已注册但未绑定 OAuth **MUST NOT** 自动绑定（防账号接管） |
| **MUST** | 改密 / 重置 **MUST** 同事务：撤销全部 refresh + 更新 `pwd_at` |

### 1.4 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/api/v1/test_auth.py` | 认证 API 端点 |
| `tools/tests/services/test_auth_service.py` | 认证服务逻辑 |
| `tools/tests/features/auth/test_auth_token_lifecycle.py` | Token 生命周期 |
| `tools/tests/features/auth/test_auth_phase1.py` | Phase 1 认证集成 |
| `tools/tests/core/test_totp.py` | TOTP 核心逻辑 |
| `tools/tests/core/test_totp_encryption.py` | TOTP 加密 |
| `tools/tests/core/test_password_compat.py` | 密码兼容性 |
| `tools/tests/core/test_token_blacklist.py` | Token 黑名单 |

---

## §2 用户管理（Users）

### 2.1 概述

用户 CRUD、自助资料与公开主页。软删除（`deleted_at` 非空）；改密与撤 refresh **MUST** 在同一事务。

| 属性 | 值 |
|------|----|
| 挂载前缀 | `/api/v1/users`、`/profile`、`/avatars` |
| 代码位置 | `app/api/v1/users.py`、`app/api/v1/profile.py`、`app/services/user_service.py` |

### 2.2 接口契约

#### 2.2.1 用户管理（管理端 + 自助）
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| GET | `/users` | `user:list` | 分页列表（默认不含已软删） |
| GET | `/users/me` | 活跃用户 | 当前用户 |
| GET | `/users/{user_id}` | `user:read` | 详情 |
| POST | `/users` | `user:create` | 创建 + 审计 |
| PUT | `/users/{user_id}` | `user:update` | 更新；改密同事务撤 refresh + 审计 |
| PUT | `/users/me` | 活跃用户 | 自助（**MUST NOT** 改 `is_active`；改密 **MUST** 带 `old_password`） |
| DELETE | `/users/{user_id}` | `user:delete` | 软删 + 撤 refresh + 审计（**MUST NOT** 自删） |

#### 2.2.2 个人资料（前端主路径）
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| GET | `/profile` | 活跃用户 | 完整资料 + 活动参与记录（`ProfileResponse`） |
| PUT | `/profile` | 活跃用户 | 更新 displayName / bio / githubUrl / websiteUrl / techTags |
| POST | `/profile/password` | 活跃用户 | 改密（旧密码 + 历史复用检测 + 全端登出） |
| POST | `/profile/avatar/preset` | 活跃用户 | 预设头像（preset_id 1–6） |
| POST | `/profile/avatar/upload` | 活跃用户 | 上传头像（≤2MB，JPEG/PNG/WebP/GIF，魔数校验） |
| GET | `/avatars/{filename}` | 公开 | 头像静态服务（文件名严格校验防路径遍历） |
| GET | `/users/{user_id}` | 公开 | 用户公开主页 + 社区/考试统计（**MUST** 仅返回已激活未软删用户） |

### 2.3 配置项与不变量

#### 2.3.1 不变量与约束（RFC 2119）
| 等级 | 约束 |
|---|---|
| **MUST** | 改密 **MUST** 同事务写 `password_changed_at` + `revoke_all_for_user()` |
| **MUST** | 自助改密 **MUST** 校验旧密码（防 access 泄露直接接管） |
| **MUST NOT** | 密码 **MUST NOT** >72 UTF-8 字节 |
| **MUST** | 软删 **MUST** 释放 username / email 唯一键（截断拼接后缀） |
| **MUST** | 头像上传 **MUST** 四重校验：大小 ≤2MB + MIME 白名单 + 扩展名白名单 + **文件头魔数** |
| **MUST NOT** | 头像文件名 **MUST** 服务端生成（**MUST NOT** 用前端原始名） |
| **MUST** | 公开主页 **MUST** 过滤：`is_active=True` 且 `deleted_at IS NULL`，否则返回 404 |

### 2.4 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/api/v1/test_users.py` | 用户 API 端点 |
| `tools/tests/services/test_user_service.py` | 用户服务逻辑 |
| `tools/tests/features/auth/test_auth_phase1.py` | 用户管理集成 |

---

## §3 RBAC（角色 / 权限）

### 3.1 概述

角色、权限 CRUD，用户↔角色 / 角色↔权限分配，权限查询。管理端点统一 `require_permission`；所有写操作 **MUST** 写入审计。

| 属性 | 值 |
|------|----|
| 挂载前缀 | `/api/v1/rbac` |
| 代码位置 | `app/api/v1/rbac/`、`app/services/rbac_service.py`、`app/middleware/rbac.py` |

### 3.2 接口契约

#### 3.2.1 角色
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| GET | `/roles` | `role:list` | 分页 `PaginatedResponse[Role]` |
| POST | `/roles` | `role:create` | 创建 + 审计 |
| GET | `/roles/{role_id}` | `role:read` | 详情 |
| PUT | `/roles/{role_id}` | `role:update` | 更新 + 审计 |
| DELETE | `/roles/{role_id}` | `role:delete` | 删除 + 审计 |

#### 3.2.2 权限
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| GET | `/permissions` | `permission:list` | 分页 |
| POST | `/permissions` | `permission:create` | 创建 + 审计 |
| GET | `/permissions/{permission_id}` | `permission:read` | 详情 |
| PUT | `/permissions/{permission_id}` | `permission:update` | 更新 + 审计 |
| DELETE | `/permissions/{permission_id}` | `permission:delete` | 删除 + 审计 |

#### 3.2.3 分配与查询
| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| POST/DELETE | `/users/{uid}/roles/{rid}` | `user:manage_roles` | 赋/撤角色 + 审计 |
| POST/DELETE | `/roles/{rid}/permissions/{pid}` | `role:manage_permissions` | 赋/撤权限 + 审计 |
| POST | `/users/{uid}/check-permission` | 活跃用户（本人/超管） | 权限校验 |
| GET | `/me/permissions` · `/me/roles` | 活跃用户 | 当前用户授权快照 |
| GET | `/users/{uid}/permissions` · `/roles` | `user:read` | 指定用户授权快照 |

### 3.3 配置项与不变量

#### 3.3.1 缓存约定
| 项目 | 规则 |
|---|---|
| 缓存键 | `rbac:user_perms:{user_id}`，TTL = 60s |
| 触发清理 | grant/revoke、角色 CRUD、权限 CRUD **MUST** 清理缓存 |
| 安全红线 | 缓存 **MUST ONLY** 用于展示/查询优化；实际授权（`require_permission`）**MUST** 每次直查 DB |

#### 3.3.2 不变量与约束（RFC 2119）
| 等级 | 约束 |
|---|---|
| **MUST** | 目标为 admin 角色或超级用户时操作者 **MUST** 是超级用户 |
| **MUST NOT** | 实际授权逻辑 **MUST NOT** 信任缓存；每次 `require_permission` 直查 DB |

### 3.4 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tests/api/v1/test_rbac.py` | RBAC API 端点 |
| `tests/services/test_rbac_service.py` | RBAC 服务逻辑 |
| `tests/middleware/test_rbac_permissions.py` | RBAC 权限中间件 |

---

## §4 审计日志（Audit）

### 4.1 概述

记录敏感管理操作（谁、何时、对什么资源做了什么）。
- 普通辅助写入：**best-effort** 独立会话
- 用户 / 角色 / 权限等敏感写：**共享请求会话 + 严格提交**，业务变更与审计 **MUST** 同事务

| 属性 | 值 |
|------|----|
| 挂载前缀 | `/api/v1/audit` |
| 代码位置 | `app/api/v1/audit.py`、`app/services/audit_service.py`、`app/models/audit_log.py` |
| Alembic 迁移 | `b8d4f02c3e15`（`audit_logs` 表） |
| 权限种子 | `system:logs` |

### 4.2 接口契约

| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/logs` | `system:logs` | 分页列表 → `PaginatedResponse[AuditLogItem]` |
| GET | `/logs/{log_id}` | `system:logs` | 详情 → `AuditLogItem` |
| DELETE | `/logs/{log_id}` | `root` | 删除单条审计日志 |
| DELETE | `/logs?before=<datetime>` | `root` | 批量删除指定时间之前 |

### 4.3 配置项与不变量

#### 4.3.1 当前写入点（action 清单）
| action | 触发位置 |
|--------|---------|
| `user.create` | `POST /users`、`POST /auth/register` |
| `user.update` | `PUT /users/{id}` |
| `user.delete` | `DELETE /users/{id}` |
| `role.create/update/delete` | RBAC 角色写操作 |
| `permission.create/update/delete` | RBAC 权限写操作 |
| `user.grant_role` / `user.revoke_role` | 用户↔角色分配 |
| `role.grant_permission` / `role.revoke_permission` | 角色↔权限分配 |

#### 4.3.2 不变量与约束（RFC 2119）
| 等级 | 约束 |
|---|---|
| **MUST** | 敏感写统一调 `record_atomic()`：共享会话、严格失败、一次提交 |
| **MUST** | 审计失败 **MUST** 回滚业务事务 |
| **MUST NOT** | 路由 **MUST NOT** 自行组合 3 个布尔开关 |
| **SHOULD** | 非关键辅助审计默认 best-effort：失败只打 warning |
| **MAY** | 超级用户 **MAY** 旁路 `require_permission`（root 权限兼容） |

### 4.4 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tests/api/v1/test_audit.py` | 审计 API 端点 |

---

## §5 工作台（Workbench）

### 5.1 概述

聚合个人效率与学习数据：GitHub 贡献热力图、API 调用统计、番茄钟专注记录、LLM 用量与用户级模型配置。

| 属性 | 值 |
|------|----|
| 挂载前缀 | `/api/v1/workbench` |
| 代码位置 | `app/api/v1/workbench.py`、`app/services/contribution_service.py`、`app/models/contribution.py`、`app/models/focus.py`、`app/models/api_usage.py`、`app/models/llm_config.py`、`app/models/llm_usage.py` |

### 5.2 接口契约

| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| GET | `/workbench/contributions/github` | 当前活跃用户 | GitHub 贡献热力图（近一年，6h 缓存，stale 降级） |
| GET | `/workbench/stats/api-usage` | 当前活跃用户 | API 调用统计：今日计数 + 近 N 天趋势 + endpoint Top10 |
| POST | `/workbench/focus-sessions` | 当前活跃用户 | 番茄钟完成一轮专注后上报 |
| GET | `/workbench/stats/pomodoro` | 当前活跃用户 | 番茄钟专注统计 |
| GET | `/workbench/stats/llm-usage` | 当前活跃用户 | 学习助手 LLM 用量 |
| GET | `/workbench/llm-config` | 当前活跃用户 | 读取用户级 LLM 配置（apiKey **MUST** 仅回显掩码） |
| PUT | `/workbench/llm-config` | 当前活跃用户 | 保存用户级 LLM 配置（API Key **MUST** AES-256-GCM 加密存储） |

### 5.3 配置项与不变量

#### 5.3.1 ContributionService 约定
| 项目 | 规则 |
|---|---|
| 抓取源 | `https://github.com/users/{username}/contributions` |
| 解析兼容 | 旧版 `<rect data-count>` 或 新版 `<td + tooltip>` |
| 缓存键 | `user_id + platform + year` → `contribution_cache` 表 |
| 缓存 TTL | 6h（`CACHE_TTL_SECONDS = 6*3600`） |
| 刷新策略 | `refresh=true` 或过期才重抓 |
| 降级 | 抓取失败 → 回退旧缓存 + `stale=true` |

#### 5.3.2 不变量与约束（RFC 2119）
| 等级 | 约束 |
|---|---|
| **MUST** | `POST /focus-sessions`：幂等不校验重复上报 |
| **MUST** | `llm-config` 读取：API Key **MUST** 仅回显掩码（前 4 后 4） |
| **MUST NOT** | 用户级 LLM API Key **MUST NOT** 明文入库或明文日志 |
| **MUST NOT** | 前端数据备份（导出/导入/清空）**MUST NOT** 提供独立后端端点 |

### 5.4 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| 工作台专属测试 | **MISSING**（已汇入 W-3 跟踪，计划 2026-09 前补齐） |

---

## §6 学习助手（Auxilio）

### 6.1 概述

rule-based + LLM 可选的学习助手。SSE 流式对话；OpenAI / Anthropic 双协议；Skills 工具调用；无 LLM 配置时降级为「学习画像 + 资源推荐」规则摘要。

| 属性 | 值 |
|------|----|
| 挂载前缀 | `/api/v1/auxilio` |
| 代码位置 | `app/api/v1/auxilio.py`、`app/services/auxilio_agent.py`、`app/services/auxilio_service.py`、`app/services/llm_client.py` |
| 核心数据表 | `conversations` / `chat_messages` / `chat_events` / `llm_usage_logs` |

### 6.2 接口契约

| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| POST | `/auxilio/chat` | 当前活跃用户 | **SSE 流式对话**（`text/event-stream`） |
| GET | `/auxilio/conversations` | 当前活跃用户 | 当前用户会话列表（按 `updated_at` 倒序） |
| GET | `/auxilio/conversations/{conversation_id}/messages` | 当前活跃用户 | 指定会话消息历史（含 `toolCalls`） |
| GET | `/auxilio/conversations/{conversation_id}/events` | 当前活跃用户 | Trajectory 事件回放 |

### 6.3 配置项与不变量

#### 6.3.1 全局配置（`.env`）
| 配置 | 说明 | 默认 |
|------|------|------|
| `LLM_PROVIDER` | 启用的 LLM 提供方。设 `none` = 纯规则模式 | `none` |
| `LLM_API_KEY` | 全局 API Key | `None` |
| `LLM_BASE_URL` | OpenAI 兼容自定义网关 URL | `None` |
| `LLM_MODEL` | 默认模型名 | `gpt-4o-mini` |
| `LLM_TIMEOUT` | 单次请求超时（秒） | `60` |
| `LLM_MAX_TOKENS` | 单次生成 max_tokens | `1024` |
| `LLM_DAILY_BUDGET` | 每日每用户 token 预算 | `200` |

#### 6.3.2 Skills 清单
| Skill id | 说明 |
|----------|------|
| `analyze_learning_profile` | 分析用户答题历史 → 薄弱知识点 + 推荐资源 |
| `get_exam_countdown` | 查询最近进行中考试 + 截止倒计时 |
| `list_tasks` | 列出已发布协会任务 |
| `list_my_claims` | 列出当前用户已认领的任务 |
| `search_resources` | 资源库模糊搜索 |
| `get_llm_usage_stats` | LLM 调用统计 |
| `get_pomodoro_stats` | 番茄钟专注统计 |
| `web_search` | 联网搜索（DuckDuckGo，`WEB_SEARCH_ENABLED` 可关） |

#### 6.3.3 Agent 预设清单
| preset_id | 名称 | 工具子集 | temperature |
|-----------|------|---------|-------------|
| `general` | 通用答疑 | 全部 8 个 | 默认 |
| `exam_sprint` | 考试冲刺 | analyze_learning_profile / get_exam_countdown / search_resources | 0.3 |
| `resource_finder` | 资源检索 | search_resources / analyze_learning_profile | 0.5 |
| `web_research` | 联网研究 | web_search / search_resources / analyze_learning_profile | 0.4 |

#### 6.3.4 不变量与约束（RFC 2119）
| 等级 | 约束 |
|---|---|
| **MUST** | LLM 未配置时降级为规则模式摘要 |
| **MUST** | 流式中途异常 **MUST** 仍发出 `error` 事件 |
| **MUST** | 会话归属校验：非本人会话 **MUST** 返回 404 |
| **MUST NOT** | 工具执行异常 **MUST NOT** 中断对话循环 |
| **MUST** | 工具循环最多 `MAX_TOOL_ROUNDS = 3` 轮 |
| **MUST** | 数据访问收敛至 `AuxilioToolRepository` |

### 6.4 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/features/tools/test_phase5_tools.py::test_auxilio` | Auxilio 学习画像分析 |

---

## §7 API 调用统计中间件（ApiUsageMiddleware）

### 7.1 概述

`app/middleware/api_usage.py` 的 `ApiUsageMiddleware` 是**纯 ASGI 埋点中间件**，fire-and-forget 把每个请求写入 `api_call_logs`。

| 属性 | 值 |
|------|----|
| 路由 | 无对外路由 |
| 注册位置 | `main.py` 中 `LoggingMiddleware` 之外层、`SecurityHeadersMiddleware` 之内层 |

### 7.2 接口契约

| 项目 | 规则 |
|------|------|
| 落库表 | `api_call_logs`（`app/models/api_usage.py`） |
| 静默跳过前缀 | `/health`、`/readyz`、`/docs`、`/openapi.json`、`/workbench/stats/api-usage` |
| endpoint 归一化 | `/api/v1/tools/exam/123` → `/api/v1/tools/exam/{id}` |
| user_id 绑定 | 当前恒为 `NULL` |

### 7.3 配置项与不变量

#### 7.3.1 不变量与约束（RFC 2119）
| 等级 | 约束 |
|---|---|
| **MUST** | 写库失败 **MUST** 静默（`create_task` + try/except） |
| **MUST NOT** | 写库失败 **MUST NOT** 阻塞主流程或修改响应状态码 |
| **MUST** | 延迟计算：响应 `http.response.start` status 时间戳 - 请求进入时间戳 |

### 7.4 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| 专属测试 | **MISSING**（已汇入 W-4 跟踪，计划 2026-09 前补齐） |

---

## Pre-commit Checklist（模块变更提交前 **MUST** 打勾）

- [ ] `make check-backend`（lint + type + 单测）全通过
- [ ] 新增 / 修改路由 **MUST** 同步 `openapi.baseline.json`（`make gen-openapi` 并对比）
- [ ] 权限要求变更（新增/删除 `require_permission`）**MUST** 同步 RBAC 权限种子迁移
- [ ] 新增配置项 **MUST** 在 `.env.example` 登记并附说明
- [ ] 敏感写操作 **MUST** 接入审计（§4.3 action 清单追加）
- [ ] RFC 2119 关键词使用合规（本文所有 MUST / MUST NOT 条款无违反）

---

> ↩ **返回后端文档地图**：[BackDoc-01-Arch.md](BackDoc-01-Arch.md) · [BackDoc-02-Sec.md](BackDoc-02-Sec.md) · [BackDoc-03-Conv.md](BackDoc-03-Conv.md) · [BackDoc-Infra.md](BackDoc-Infra.md) · **全栈部署**：[RootDoc-Deploy.md](../../../docs/RootDoc-Deploy.md) · **工程约定**：[RootDoc-EngConv.md](../../../docs/RootDoc-EngConv.md)