# BackDoc-02-Sec：后端安全与防护（Reference · 鉴权/异常/限流/密钥的权威定义）

> 更新人：3yearsZ
> 更新日：2026-08-20
> 版本：1.0.1 · 七夕（Diátaxis R 类规范，安全约束 SSOT 权威）
> Diátaxis：R（Reference · 回答「是什么」，提供后端安全机制的接口、配置、不变量的精确权威定义；不包含可执行步骤）
> 适用读者：安全审计人员 / 后端开发者 / 运维部署者 / RBAC 权限设计者
> 变更触发：`app/core/security.py` 签名变更 / `.env` 安全配置项增删 / 限流策略调参 / 新增 `require_permission` 资源点 / 密钥轮换流程修改

> **SSOT 分工声明**：
> - 本文档是「**后端运行时安全机制（鉴权/异常/限流/密钥/扩展安全）**」的唯一权威（SSOT）。
> - 前端 BFF 层安全（Origin 校验/UI 路由兜底/安全头）→ [FrontDoc-02-Sec.md](../../../CS-Web-Frontend/tools/docs/FrontDoc-02-Sec.md)。
> - 安全深层威胁模型（STRIDE 15 条）→ [CS-Mobile/tools/docs/arch/安全设计.md](../../../CS-Mobile/tools/docs/arch/安全设计.md)。
> - 基础设施契约（日志/数据库/缓存）→ [BackDoc-Infra.md](BackDoc-Infra.md)。
> - 业务模块契约（接口/RBAC）→ [BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md)。
> - 工程约定（分层/命名）→ [BackDoc-03-Conv.md](BackDoc-03-Conv.md)。

> **治理红线**：
> - MUST 所有安全约束在代码、配置、CI 门禁中落地；正文与实现不一致时，以本节约束为准
> - MUST NOT 在日志、异常响应、埋点中打印 token、密码明文、bcrypt 哈希、TOTP secret
> - MUST 新增 `require_permission` 资源点时同步更新 `rbac_seed_data.py` 和数据库唯一约束
> - MUST NOT 生产环境 `JWT_ACCEPT_LEGACY_TOKENS=True` 停留超过 30 分钟窗口

---

## 快速索引

| 安全领域 | 概述 | 接口/配置 | 不变量(RFC2119) | 自检 Checklist | 代码位置 |
|---|---|---|---|---|---|
| **§1 鉴权与安全基础设施** | JWT 双 token + RBAC0 授权 | §1.2 | §1.3 | §1.4 | `app/core/security.py`、`middleware/rbac.py` |
| **§2 异常处理契约** | BaseAppException + ErrorCode SSOT | §2.2 | §2.3 | §2.4 | `app/core/exceptions/`、`error_codes.py` |
| **§3 请求限流** | 全局 + 认证双层窗口 | §3.2 | §3.3 | §3.4 | `app/core/rate_limit/`、`middleware/rate_limit.py` |
| **§4 密钥与凭证管理** | `.env` 注入 + 轮换 Runbook | §4.2 | §4.3 | §4.4 | `.env`、`app/core/config.py` |
| **§5 扩展功能安全** | LLM/OAuth/埋点/RBAC 初始化 | §5.2 | §5.3 | §5.4 | `app/services/auxilio_agent.py`、`middleware/api_usage.py` |
| **§6 变更门禁** | Pre-commit 必查清单 | — | — | §6 | — |

---

## §1 鉴权与安全基础设施

### 1.1 概述

后端签发并校验 Bearer JWT 双 token，基于 bcrypt 完成密码哈希，通过 Redis + 进程内存双层黑名单实现 access 撤销，使用 `require_permission(resource, action)` 依赖强制 RBAC0 授权。所有业务 API **MUST** 经由 `get_current_user` 注入当前用户上下文。

### 1.2 接口与配置清单

| 符号 / 配置项 | 签名 / 默认值 | 用途 |
|---|---|---|
| `create_access_token` | `create_access_token(data) -> (token, jti, exp)` | 签发 access JWT |
| `verify_token` | `verify_token(token) -> dict \| None` | 校验签名、issuer、audience、`token_type=access`、`exp` |
| `async_get_password_hash` | `await async_get_password_hash(password)` | 在线程池执行 bcrypt |
| `async_verify_password` | `await async_verify_password(raw, hashed)` | 恒定时间防时序攻击 |
| `get_current_user` | FastAPI dependency | 解析 token → 回查用户激活态 → 回查 jti 黑名单 |
| `require_permission` | `require_permission(resource, action)` | 细粒度 RBAC0 依赖 |
| `SECRET_KEY` | 环境变量，长度 ≥ 32 字节 | JWT HS256 签名密钥 |
| `JWT_PREVIOUS_SECRET_KEYS` | 空字符串 | 透明兼容旧 token 的轮换窗口期 |
| `JWT_ISSUER` / `JWT_AUDIENCE` | 字符串 | 签发/校验一致性校验 |
| `JWT_ACCEPT_LEGACY_TOKENS` | `False` | 迁移窗口临时开启；**MUST NOT** 长期保留 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | access 短时效；**MUST NOT** 超过 60 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | refresh 长时效；**MUST NOT** 超过 30 |
| `TOKEN_BLACKLIST_FALLBACK` | `closed` | Redis 不可用时的行为；`open` 仅开发调试 |
| `REQUIRE_REDIS_FOR_SECURITY` | `True`（生产强制） | 多 worker 下撤销一致性硬开关 |

### 1.3 不变量与约束（RFC2119）

**MUST（铁律红线）：**
1. 新签发的 JWT **MUST** 携带 `iss`、`aud`、`iat`、`jti`、`token_type=access`、`exp` 六项声明
2. 所有 bcrypt 哈希/校验调用 **MUST** 走 `async_get_password_hash` / `async_verify_password` 线程池封装
3. bcrypt 输入 **MUST** 限制 ≤ 72 UTF-8 字节；超过部分截断并记录警告日志
4. `get_current_user` **MUST** 依次校验：token 签名有效 → 用户 `is_active=True` → 用户任一角色 `is_active=True` → jti 不在黑名单
5. 多 worker 部署且要求即时撤销一致性时，**MUST** 开启 `REQUIRE_REDIS_FOR_SECURITY=True`
6. `inactive` 用户 **MUST NOT** 授予任何访问权限；`inactive` 角色 **MUST NOT** 参与权限计算
7. RBAC0 **MUST** 在服务端 enforce，即 `require_permission` 以 FastAPI dependency 在路由层硬绑定
8. 新增权限资源点 **MUST** 同步更新 `rbac_seed_data.py` 并加 `resource:action` 数据库唯一约束
9. 密码校验失败与成功的响应时间差 **MUST** 被 bcrypt 恒定时间比较与 2FA 预认证 token 掩盖
10. JWT 签名算法 **MUST** 固定为 HS256（显式声明），**MUST NOT** 接受 `alg=none` 或外部指定的弱算法头

**MUST NOT（禁止事项）：**
1. **MUST NOT** 硬编码 `SECRET_KEY`、`TOTP_ENCRYPTION_KEY`、`DATABASE_PASSWORD` 到代码或 Git 仓库
2. **MUST NOT** 在日志、异常响应体、错误消息、埋点中打印 access/refresh token、密码明文、bcrypt 哈希值、TOTP secret
3. **MUST NOT** 通过 URL query string 传递 token、密码、TOTP 验证码
4. **MUST NOT** 让 `JWT_ACCEPT_LEGACY_TOKENS=True` 在生产停留超过 30 分钟窗口
5. **MUST NOT** 允许 `user_id`、`is_admin`、`role` 等身份字段从客户端请求参数直接注入
6. **MUST NOT** 把 `current_user.is_active` 检查放到单个业务路由；必须在依赖注入层统一完成

**SHOULD（建议事项）：**
1. access 有效期 **SHOULD** 维持 15 分钟；确需延长 **SHOULD NOT** 超过 30 分钟
2. refresh 轮换策略 **SHOULD** 每次 `/auth/refresh` 调用都返回一对全新双 token
3. 撤销黑名单 **SHOULD** 采用双层回查：先 Redis 再进程内存
4. 管理员创建 `ADMIN_PASSWORD` **SHOULD** 启动后 24 小时内由首登管理员立即修改

**MAY（可选配置）：**
1. 单 worker 且用户规模 < 50 的开发测试部署，**MAY** 临时关闭 `REQUIRE_REDIS_FOR_SECURITY`
2. 特定场景（如 SSO 迁移窗口）**MAY** 临时开启 `JWT_ACCEPT_LEGACY_TOKENS=True`

### 1.4 自检 CheckList

- [ ] 新增/修改签发逻辑时，已同步校验 §1.2 中 6 项 JWT 声明是否齐全
- [ ] 任何涉及 password / token 的代码变更，已 grep 确认无 `print()` / 日志明文输出
- [ ] `require_permission` 新增资源点，已同步登记 `rbac_seed_data.py` + Alembic seed 数据
- [ ] 配置项变更后，`.env.example` 模板与 `config.py` 默认值保持双写一致
- [ ] 本节 10 条 MUST 约束，在 `tools/tests/core/test_security.py` / `test_rbac_permissions.py` 中有对应反向测试用例

---

## §2 异常处理契约

### 2.1 概述

业务失败统一以 `BaseAppException` 子类表达，由全局 handler 映射为稳定 `ClientError` 响应体；最外层 `ExceptionHandlerMiddleware` 兜底路由层外异常。`ErrorCode` 注册表是客户端错误码的单一事实源（SSOT）。

### 2.2 接口与配置清单

| 符号 | 用途 | 关联文件 |
|---|---|---|
| `BaseAppException` | 业务异常基类 | `app/core/exceptions/base_exceptions.py` |
| `ErrorCode` | 客户端错误码枚举；命名空间 = `{领域}_{7位数字}` | `app/core/exceptions/error_codes.py` |
| `setup_exception_handlers(app)` | 注册业务异常、Pydantic 校验、HTTP 4xx/5xx、DB 异常、兜底 handler | `app/core/exceptions/handlers.py` |
| `ExceptionHandlerMiddleware` | ASGI 中间件，捕获路由层外异常 | `app/core/exceptions/middleware.py` |
| `ExceptionLogRepo` | 独立 DB 会话异步持久化异常日志 | `app/repositories/exception_log_repo.py` |
| `/api/v1/exceptions` | 超级用户查询异常日志端点 | `app/api/v1/exceptions.py` |

### 2.3 不变量与约束（RFC2119）

**MUST（铁律红线）：**
1. 路由层业务异常 **MUST** 继承 `BaseAppException` 并引用 `ErrorCode.*` 枚举值
2. 异常中间件短路响应 **MUST** 使用 `JSONResponse` 返回；**MUST NOT** 抛出 `HTTPException`
3. Pydantic 校验错误 **MUST** 移除原始 `input` 字段后再输出
4. 数据库异常（IntegrityError / OperationalError 等）**MUST** 仅返回稳定通用消息
5. 异常日志持久化 **MUST** 使用独立数据库会话；写入失败 **MUST** 降级为应用日志记录
6. 日志 **MUST** 只记录归一化请求路径，避免 token、手机号、邮箱泄露
7. `ErrorCode` **MUST** 全局唯一（`{字母域前缀}_{7位数字}`）

**MUST NOT（禁止事项）：**
1. **MUST NOT** 在路由、service 层裸 `try/except: pass` 或空 catch 静默吞错
2. **MUST NOT** 在异常响应体、异常日志中包含 `.env` 密钥、DB 连接串内部 IP、内部路径堆栈
3. **MUST NOT** 允许路由函数返回非标准格式的自定义错误 JSON
4. **MUST NOT** 把 5xx 业务失败降级为 200 成功响应带 `success=false`
5. **MUST NOT** 在 Alembic 迁移外调用 `Base.metadata.create_all()` 建表

**SHOULD（建议事项）：**
1. **SHOULD** 把异常分类映射到可重试标记
2. **SHOULD** 为敏感操作的异常增加 `security_details` 字段（仅 superuser 可见）
3. **SHOULD** 异常日志写入速率被独立限流（如 100/分钟/实例）

### 2.4 自检 CheckList

- [ ] 新增业务异常类时，已在 `base_exceptions.py` 定义 + `error_codes.py` 注册唯一编号
- [ ] 所有 `try/except` 已检查，无空 catch
- [ ] §2.3 5 条 MUST NOT 约束，在 `tools/tests/core/test_exception_handlers.py` 中反向覆盖
- [ ] 异常 handler 数量变动后，已确认 `setup_exception_handlers` 注册顺序正确

---

## §3 请求限流

### 3.1 概述

限流以「全局窗口（所有请求） + 认证窗口（登录/注册/refresh）」双层执行；后端优先 Redis 共享计数，未配置或故障时降级为进程内存计数。客户端 IP 仅从可信反代网段的转发头解析，避免伪造 IP 绕过限流。

### 3.2 接口与配置清单

| 符号 / 配置项 | 默认值 | 用途 |
|---|---|---|
| `get_client_ip(request, trusted_proxies=()) -> str` | — | 从右向左跳过可信代理链，取第一个不可信来源 IP |
| `RateLimitMiddleware` | `calls=100, period=60` | 全局限流中间件 |
| `AuthRateLimitMiddleware` | `calls=5, period=60` | 认证端点限流 |
| `RATE_LIMIT_CALLS / RATE_LIMIT_PERIOD` | 100 / 60 | 全局窗口环境变量覆写 |
| `AUTH_RATE_LIMIT_CALLS / AUTH_RATE_LIMIT_PERIOD` | 5 / 60 | 认证窗口环境变量覆写 |
| `TRUSTED_PROXY_CIDRS` | 空元组 | 可信反向代理 CIDR |
| `REDIS_URL` | — | 限流共享后端；未配置时自动降级 |
| 超限响应 | 429 JSON + `Retry-After` header | 统一返回 `C429001 请求过于频繁，请稍后重试` |

### 3.3 不变量与约束（RFC2119）

**MUST（铁律红线）：**
1. 客户端 IP 解析 **MUST** 仅在直连来源落入 `TRUSTED_PROXY_CIDRS` 可信网段时，才读取 `X-Forwarded-For` / `X-Real-IP`
2. 可信代理链解析 **MUST** 从右向左跳过 `TRUSTED_PROXY_CIDRS` 内连续条目
3. 认证端点 **MUST** 叠加 `AuthRateLimitMiddleware`（默认 5/60s），独立于全局限流
4. 超限响应 **MUST** 返回 `429` 状态码 + `Retry-After` header + 统一错误码 `C429001`
5. Redis 是否可用 **MUST NOT** 成为启动硬依赖；**MUST** 自动降级到进程内存计数

**MUST NOT（禁止事项）：**
1. **MUST NOT** 把 `TRUSTED_PROXY_CIDRS` 配置为 `0.0.0.0/0` 或过宽公网网段
2. **MUST NOT** 允许限流键只取 user_id 不取 client_ip
3. **MUST NOT** 对限流计数键使用可枚举的自增 ID 或预测值
4. **MUST NOT** 让限流中间件抛出 `HTTPException`

**SHOULD（建议事项）：**
1. **SHOULD** 在反代层额外叠加南北向 20 QPS 全局限流
2. **SHOULD** 对连续被限流 10 次以上的 IP 写入 WAF 临时黑名单
3. **SHOULD** 限流命中计数定期上报 Prometheus metrics

### 3.4 自检 CheckList

- [ ] `TRUSTED_PROXY_CIDRS` 已按部署环境真实反代网段填写
- [ ] `tools/tests/middleware/test_rate_limit.py` 反向覆盖四类场景均有断言
- [ ] 429 响应体格式与 §2 统一错误响应一致
- [ ] 新增端点被确认为认证相关后，已追加到 `AuthRateLimitMiddleware` 的路径清单

---

## §4 密钥与凭证管理

### 4.1 概述

所有高敏凭证（JWT 签名密钥、TOTP 加密密钥、DB 密码、社区 IP 哈希密钥）仅存 `.env`（权限 0600），通过 compose 环境变量注入容器，禁止硬编码或打包进镜像。本节同时定义四类密钥的轮换 Runbook 与记录模板。

### 4.2 密钥清单与保护分级

| 密钥 | 环境变量 | 级别 | 轮换周期 | 代码入口 |
|---|---|---|---|---|
| JWT 签名密钥 | `SECRET_KEY` | L4 高敏 | ≤ 6 个月 | `app/core/security.py` |
| TOTP 加密密钥 | `TOTP_ENCRYPTION_KEY` | L4 高敏 | ≤ 6 个月 | `app/core/totp_encryption.py` |
| 数据库密码 | `DATABASE_PASSWORD` | L4 高敏 | ≤ 3 个月 | docker-compose + `app/core/config.py` |
| 社区 IP 哈希密钥 | `COMMUNITY_IP_HASH_SECRET` | L3 敏感 | ≤ 12 个月 | `app/services/community_service.py` |
| 2FA 种子（单用户） | `two_factor_auths.secret_encrypted` | L3 敏感 | 随用户重设 | 列级加密（AES-256-GCM） |
| Refresh token（单用户） | `refresh_tokens.token_hash` | L3 敏感 | 7 天自然过期 | sha256 存库 |
| 第三方 OAuth 密钥 | `GITHUB_CLIENT_SECRET` / `SMTP_PASSWORD` | L4 高敏 | 第三方账号变更时 | `.env` + `oauth_service.py` |
| LLM API Key | `LLM_API_KEY`（全局）/ `llm_configs.api_key_encrypted`（用户级） | L4 高敏 | 用户主动撤销 | `.env` + AES 列级加密 |

### 4.3 不变量与约束（RFC2119）

**MUST（铁律红线）：**
1. 所有 L4 级密钥 **MUST** 仅通过 `.env` 环境变量注入；**MUST NOT** 出现在 `Dockerfile` `ENV` 指令、Git 仓库、备份明文、CI log
2. `.env` 文件权限 **MUST** 为 0600（仅 owner 可读）
3. Docker 镜像构建 **MUST** 在 `.dockerignore` 中排除 `.env`
4. `SECRET_KEY`、`TOTP_ENCRYPTION_KEY`、`COMMUNITY_IP_HASH_SECRET` **MUST** 长度 ≥ 32 字节
5. `COMMUNITY_IP_HASH_SECRET` **MUST** fail-fast：缺失直接拒绝启动
6. 轮换高敏密钥后 **MUST** 填写轮换记录模板
7. 人员离职或密钥疑似泄露时 **MUST** 立即启动应急轮换
8. 备份文件 **MUST** 使用 openssl AES-256 加密后再离线存储
9. 用户自有 LLM API Key **MUST** 加密后落 `llm_configs.api_key_encrypted` 列

**MUST NOT（禁止事项）：**
1. **MUST NOT** 把 `.env` 加入 Git；`.gitignore` 必须显式列出 `.env`、`.env.local`、`*.env.*`
2. **MUST NOT** 通过 GitHub Actions / Jenkins log 输出环境变量
3. **MUST NOT** 在部署文档、运行手册、邮件、即时消息中传递明文密钥
4. **MUST NOT** 把 `SECRET_KEY` 同时用于 JWT 签名 + TOTP 加密 + 社区 IP 哈希
5. **MUST NOT** 在 `JWT_PREVIOUS_SECRET_KEYS` 中永久保留旧密钥
6. **MUST NOT** 在容器内运行的应用日志中打印完整环境变量列表
7. **MUST NOT** 允许非管理员用户通过任何接口查询 `.env` 项或配置值

**SHOULD（建议事项）：**
1. **SHOULD** 实现 TOTP 双密钥解密窗口期（类似 `JWT_PREVIOUS_SECRET_KEYS`）
2. **SHOULD** 对 `.env` 变更引入「变更前备份 + 变更后 make check-config」两步流程
3. **SHOULD** DB 密码与 JWT/TOTP 密钥错峰轮换
4. **SHOULD** 把 `DATABASE_PASSWORD` 变更纳入 db migrations 流水线
5. **SHOULD** 轮换 JWT 密钥后，主动推送系统通知

### 4.4 自检 CheckList

- [ ] §4.3 9 条 MUST 约束，在 `tools/tests/` 中有对应的 fail-fast 启动测试
- [ ] `.gitignore` 已 grep 确认 `.env` / `.env.local` / `*.env.*` 全部被排除
- [ ] 每类 L4 密钥指纹已登记在运维笔记本；轮换后记录模板已归档
- [ ] 新增高敏环境变量后，已同步到根级 + 后端 `.env.example` 双模板

---

## §5 扩展功能安全

### 5.1 概述

Auxilio LLM 学习助手、`api_usage` 匿名埋点中间件、GitHub OAuth 登录、RBAC 启动种子四项扩展功能，均须在不扩大既有信任边界的前提下安全运行。

### 5.2 接口与配置清单

| 模块 | 配置项 | 默认值 | 安全基线 |
|---|---|---|---|
| Auxilio LLM | `LLM_PROVIDER` | `none` | `none` 时只走本地规则模式，不发起任何外部 HTTP |
| Auxilio LLM | `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_TIMEOUT` / `LLM_MAX_TOKENS` | 空 / 空 / `gpt-4o-mini` / 60s / 1024 | 全局 `.env` 注入 |
| Auxilio LLM | `LLM_DAILY_BUDGET` | 200（次/用户/天） | 单用户预算；0 = 不限制 |
| 用户级 LLM Key | `llm_configs.api_key_encrypted` | 加密列 | AES-GCM 加密，仅用户本人调用 decrypt |
| api_usage 埋点 | `app/middleware/api_usage.py` 字段 | `endpoint/method/status/latency_ms/created_at` | user_id 恒为 NULL，完全匿名 |
| GitHub OAuth | `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | 空 | 缺失时入口直接返回 `OAUTH_NOT_CONFIGURED` 400 |
| RBAC 初始化 | `rbac_seed` startup 任务 | priority=20, critical=True | PostgreSQL advisory lock 单实例执行 |

### 5.3 不变量与约束（RFC2119）

**MUST（铁律红线）：**
1. 当 `LLM_PROVIDER=none` 或全局 `LLM_API_KEY` 缺失且用户无自有 Key 时，Auxilio 对话入口 **MUST** 直接抛出 `LLMConfigError` 并降级为本地规则模式
2. 所有 Auxilio 接口 **MUST** 经 `get_current_active_user` 鉴权
3. 用户级 LLM API Key **MUST** 经 `totp_encryption.encrypt_secret` 加密落 `api_key_encrypted`
4. `api_usage` 埋点 **MUST** 仅记录 `endpoint/method/status/latency_ms/created_at` 五字段
5. `api_usage` 埋点 **MUST** 以 `asyncio.create_task` fire-and-forget 执行
6. GitHub OAuth **MUST** 在 `GITHUB_CLIENT_ID` 缺失时返回 `OAUTH_NOT_CONFIGURED` 状态码 400
7. OAuth 回调流程 **MUST** 校验 `state` 参数防止 CSRF
8. RBAC 启动 seed **MUST** 通过 PostgreSQL advisory lock 保证多 worker 下仅一个实例创建默认管理员

**MUST NOT（禁止事项）：**
1. **MUST NOT** 在 LLM prompt 中注入完整用户数据、会话历史中的其他用户消息、或完整数据库内容
2. **MUST NOT** 让 LLM 工具调用具备写数据库、发邮件、调管理员接口的能力
3. **MUST NOT** 在 `api_call_logs` 中写入用户身份
4. **MUST NOT** 允许 `ADMIN_PASSWORD` 通过任何 API 接口回显或修改
5. **MUST NOT** 允许 OAuth 用户跳过邮箱密码登录体系直接创建管理员角色
6. **MUST NOT** 把 GitHub OAuth 的 `state` 参数复用为 CSRF token 之外用途

**SHOULD（建议事项）：**
1. 用户级 LLM Key **SHOULD** 支持「测试连接」按钮
2. LLM 全局 200 次/天预算 **SHOULD** 接入独立 Redis 计数窗口
3. GitHub OAuth **SHOULD** 审计日志记录「谁在何时用 OAuth 登录成功/失败、从哪个 IP」
4. RBAC 默认管理员账号 **SHOULD** 在首次启动后 72 小时内由首登管理员强制改密码

### 5.4 自检 CheckList

- [ ] LLM 工具调用集已审计：全部只读，无 DB 写 / 邮件发 / 管理员操作
- [ ] `api_usage` 埋点字段已 grep 确认：user_id 恒为 NULL
- [ ] GitHub OAuth state CSRF 校验 + 服务端换 token：在 `tools/tests/integration/test_oauth.py` 有反向用例
- [ ] RBAC seed 在并发 10 实例启动测试下仅 1 个成功

---

## §6 变更门禁

> 本章为 Pre-commit 必查清单。每次提交涉及安全的代码/配置变更前，提交人 **MUST** 逐项自查并在 PR 描述中打钩；CR 审核人 **MUST** 核对本清单并在未打钩时打回。

### §6.1 通用门禁

- [ ] 变更是否影响 §1-§5 中任一 MUST/MUST NOT 约束？若是，本节约束文字 **MUST** 已同步更新
- [ ] 新增/修改接口的 OpenAPI schema 是否已走 `make contract-baseline` 更新基线
- [ ] `.env` 配置项变更是否已同步更新：根级 `.env.example` + 后端 `CS-Web-Backend/.env.example` + `app/core/config.py` 默认值 三处对齐
- [ ] 版本号、变更日期是否已在本文档 6 行元数据头同步更新
- [ ] `gen_doc_facts.py` 派生事实同步（`make gen-doc-facts`）：Alembic head / 版本一致性 / 模块契约对齐 / 测试存在 四项无漂移

### §6.2 鉴权变更门禁（§1 相关）

- [ ] 签发/校验逻辑变更后，`tools/tests/core/test_security.py` 全量通过
- [ ] 新 token 声明是否与 `JWT_ISSUER / JWT_AUDIENCE / token_type` 兼容性校验一致
- [ ] 密码哈希调用是否全部走线程池封装
- [ ] RBAC 资源点变更是否已同步更新 `rbac_seed_data.py` + Alembic seed 数据

### §6.3 异常契约变更门禁（§2 相关）

- [ ] 新增异常类是否三要素齐全：基类继承 + `ErrorCode` 唯一注册 + `__init__.py` 导出
- [ ] 客户端错误码在前端 `FrontDoc-02-Sec.md` 错误码映射表是否已同步更新
- [ ] Pydantic 校验错误回显 `input` 的过滤逻辑是否仍然生效

### §6.4 限流配置变更门禁（§3 相关）

- [ ] `TRUSTED_PROXY_CIDRS` 变更是否已和实际反代网段对账
- [ ] 认证限流窗口调大时，防爆破效果是否仍然满足「5 次失败锁定/告警」的底线
- [ ] 反代层南北向限流与后端限流的阈值分层是否仍然合理

### §6.5 密钥管理门禁（§4 相关）

- [ ] 高敏密钥提交前，Git 历史 `git log -p -S "SECRET_KEY"` 检查：确认无明文提交
- [ ] `.dockerignore` / `.gitignore` 未遗漏密钥类文件
- [ ] 轮换后记录模板是否已归档到运维安全日志
- [ ] `make check-config` 启动校验：所有 ≥ 32 字节的 L4 密钥长度达标

### §6.6 扩展功能门禁（§5 相关）

- [ ] LLM 工具调用集新增成员：已 review 是否为只读 + 不可越权
- [ ] 埋点中间件字段变更：`user_id` 仍为 NULL + 无 body/header/PII
- [ ] OAuth 登录：state CSRF 校验 + 服务端换 token 双重保障未被绕过
- [ ] 默认管理员：critical=True + advisory lock 双保险仍生效

---

> ↩ **返回后端文档地图**：[BackDoc-01-Arch.md](BackDoc-01-Arch.md) · [BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md) · [BackDoc-03-Conv.md](BackDoc-03-Conv.md) · [BackDoc-Infra.md](BackDoc-Infra.md) · **前端安全**：[FrontDoc-02-Sec.md](../../../CS-Web-Frontend/tools/docs/FrontDoc-02-Sec.md)