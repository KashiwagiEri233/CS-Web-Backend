# BackDoc-02-Sec：安全与防护（鉴权 / 异常 / 限流）

> 文档定位：**后端**的安全与防护权威文档（reference）
> 受众：安全审计人员 / 后端开发工程师 / 运维 / 权限设计者
> Source of truth：**后端**的鉴权基础设施、异常处理契约、请求限流配置
> 关联：架构见 [BackDoc-01-Arch.md](BackDoc-01-Arch.md)；基础设施见 [BackDoc-Infra.md](BackDoc-Infra.md)；编码规范见 [BackDoc-Conv.md](BackDoc-Conv.md)；前端 BFF 层安全与 UI 路由保护见 [FrontDoc-02-Sec.md](../../../CS-Web-Frontend/tools/docs/FrontDoc-02-Sec.md)
> 最后更新：2026-08-08（0.9.8 同步：学习助手 LLM / api_usage 隐私 / GitHub OAuth / RBAC / 新表迁移）
> 更新人：3yearsZ
> 变更触发：后端鉴权契约变更 / 安全配置变更 / 限流策略变更 / 新增权限点
> Stale 信号：接口签名与 `app/core/security.py` 等实现不一致 / 配置项未随环境变量变更更新 / 仍把前端 BFF 职责（Origin 校验/UI 角色兜底）写成后端职责

> **范围声明**：本文档仅覆盖**后端**运行时安全责任。前端 BFF 层（Origin 校验、Cookie 托管、UI 角色路由保护、按钮显隐）见前端 `FrontDoc-02-Sec.md`；后端承载 JWT 签发与校验、密码哈希（bcrypt）、TOTP/2FA 加密与验证、RBAC `require_permission` 强制、速率限制、审计日志写入、session/refresh_token 表。

---

## 1. 鉴权与安全基础设施

### 1.1 概述

覆盖 PyJWT 签发与校验、密码哈希、access token 黑名单、当前用户解析以及 RBAC
权限依赖。业务 API 仍通过 `require_permission(resource, action)` 声明授权要求。

代码：`app/core/security.py`、`app/core/security_blacklist.py`、`app/middleware/rbac.py`、`app/core/password_compat.py`。

### 1.2 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `create_access_token` | `create_access_token(data) -> (token, jti, exp)` | 签发 access token |
| `verify_token` | `verify_token(token) -> dict \| None` | 校验签名、issuer、audience 和 access token 类型 |
| `async_get_password_hash` | `await async_get_password_hash(password)` | 在线程池执行 bcrypt |
| `async_verify_password` | `await async_verify_password(raw, hashed)` | 在线程池校验 bcrypt |
| `get_current_user` | FastAPI dependency | 解析 token、用户及撤销状态 |
| `require_permission` | `require_permission(resource, action)` | 构造细粒度权限依赖 |

### 1.3 配置

关键配置：`SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEYS`、`JWT_ISSUER`、`JWT_AUDIENCE`、
`JWT_ACCEPT_LEGACY_TOKENS`、token 有效期、`TOKEN_BLACKLIST_FALLBACK`、`REQUIRE_REDIS_FOR_SECURITY`。

### 降级与不变量

- 新 token 必须携带 `iss`、`aud`、`iat`、`jti` 和 `token_type`。
- 旧 token 兼容仅用于迁移窗口；`JWT_ACCEPT_LEGACY_TOKENS` 默认关闭。所有 token 强制 `exp`（缺失即拒绝）。
- 黑名单 Redis 恢复后仍回查进程内存，覆盖降级窗口内本进程拉黑的 jti（`fallback="open"` 除外）。
- 多 worker 且要求即时撤销一致性时，必须配置 Redis 并开启 `REQUIRE_REDIS_FOR_SECURITY`：校验期强制 `REDIS_URL`、强制 `TOKEN_BLACKLIST_FALLBACK=closed`、Redis 不可用时启动拒绝（fail-closed）。
- bcrypt 输入限制为 72 UTF-8 字节；哈希不得阻塞事件循环。
- inactive 用户和 inactive 角色都不能授予访问权限。

### 1.5 测试

`tools/tests/core/test_security.py`、`test_token_blacklist.py`、`tools/tests/middleware/test_rbac_permissions.py`、
`tools/tests/integration/test_http_postgres_e2e.py`、`test_redis_backends.py`。

### 1.6 扩展指引

新增安全声明时同时更新签发、校验和反向测试；新增权限必须登记 seed 数据并通过 `resource:action` 唯一约束。

---

## 2. 异常处理

### 2.1 概述

用 `BaseAppException` 子类表达业务失败，由全局处理器转换为统一错误响应；未处理异常由最外层异常中间件兜底。
错误码集中在 `ErrorCode` 注册表，异常日志异步持久化，避免路由自行拼装错误 JSON。

代码：`app/core/exceptions/`、`app/models/exception_log.py`、`app/repositories/exception_log_repo.py`。

### 2.2 接口

| 符号 | 用途 |
|---|---|
| `BaseAppException` | 业务异常基类，承载状态码、错误码、消息和安全详情 |
| `ErrorCode` | 客户端错误码的单一事实源 |
| `setup_exception_handlers(app)` | 注册业务异常、FastAPI 校验、HTTP、数据库和兜底处理器 |
| `ExceptionHandlerMiddleware` | 捕获路由层外异常并按状态映射统一响应 |

异常日志查询接口挂载于 `/api/v1/exceptions`（仅供超级用户），契约以 `app/api/v1/exceptions.py` 与 `app/schemas/exception_log.py` 为准。

### 2.3 响应与安全

统一错误响应包含 `success=false`、`error_code`、`message`、`status_code`、`timestamp`，按异常类型可带安全 `details`。

- Pydantic 校验错误移除原始 `input`，避免密码、令牌回显或落日志。
- 数据库异常只返回稳定错误码和通用消息，不返回驱动异常/SQL/约束原文。
- 日志记录请求路径，不记录带查询参数的完整 URL。
- 业务异常必须引用 `ErrorCode.*`，禁止裸字符串错误码。
- 中间件短路用 `JSONResponse`，不抛 `HTTPException`。

### 2.4 持久化与降级

异常日志通过独立数据库会话写入，失败只写应用日志，不覆盖原始 HTTP 响应。表结构由 Alembic 维护；应用代码和测试不得调用 `create_all`。

### 2.5 扩展指引

1. 在 `base_exceptions.py` 定义或复用异常类。
2. 在 `error_codes.py` 对应命名空间登记错误码。
3. 从 `app/core/exceptions/__init__.py` 导出公共异常。
4. 仅需专属转换逻辑时才在 `setup_exception_handlers` 注册处理器。
5. 补充 handler、middleware 和 service 层测试。

### 测试

`tools/tests/core/test_exception_handlers.py`、`test_exception_handler_middleware.py`、`test_exception_logging.py`、`tools/tests/services/test_exception_service.py`。

---

## 3. 请求限流

### 3.1 概述

限流后端优先 Redis（多实例共享计数），未配置或故障时降级为进程内存。
全局限流覆盖所有请求，认证限流额外覆盖登录、注册和 refresh 端点。

代码：`app/core/rate_limit/`、`app/middleware/rate_limit.py`；客户端 IP 解析见 `app/core/request_context.py`。

### 3.2 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_client_ip` | `get_client_ip(request, trusted_proxies=()) -> str` | 从可信代理链解析真实客户端 IP |
| `RateLimitMiddleware` | `RateLimitMiddleware(app, calls, period, limit_paths=None)` | 全局或指定路径限流 |
| `AuthRateLimitMiddleware` | `AuthRateLimitMiddleware(app, calls, period)` | 认证端点严格限流 |

超限返回统一 `429` JSON 和 `Retry-After`，中间件不抛 `HTTPException`。

### 3.3 配置

- `RATE_LIMIT_CALLS` / `RATE_LIMIT_PERIOD`：全局窗口。
- `AUTH_RATE_LIMIT_CALLS` / `AUTH_RATE_LIMIT_PERIOD`：认证窗口。
- `TRUSTED_PROXY_CIDRS`：可信反向代理 CIDR；为空忽略 `X-Forwarded-For`/`X-Real-IP`。
- `REDIS_URL` 及 Redis 超时/重试配置：控制共享后端和故障降级。

只有直连来源处于可信网段时才读取转发头，并从右向左跳过可信代理，取第一个不可信地址。部署在反向代理后应填写实际代理网段，不用过宽公网网段。

### 3.4 降级与不变量

- Redis 是增强项，不是启动依赖；故障后限流退化为单进程语义。
- 不可信来源的转发头绝不参与限流键计算。
- 多 worker 且无 Redis 时各进程独立计数。

### 3.5 测试

`tests/middleware/test_rate_limit.py`：普通限流、严格认证限流、可信/不可信代理解析、Redis 降级。

---

## 4. 密钥轮换 Runbook

> **合并说明**：本章原位于 `BackDoc-KeyRotation.md`（密钥轮换 Runbook），于 2026-08-07 并入本文 §4，与 §1 鉴权基础设施的密钥配置（SECRET_KEY / TOTP_ENCRYPTION_KEY / DATABASE_PASSWORD）形成完整闭环。
> 适用范围：CS-Web-Backend 生产环境
> 触发条件：定期轮换（建议每 6 个月）/ 安全事件（疑似泄露）/ 人员变动

### 4.1 密钥清单

| 密钥 | 环境变量 | 轮换影响 | 紧急度 |
|------|----------|----------|--------|
| JWT 签名密钥 | `SECRET_KEY` | 全部 access/refresh token 失效，用户需重新登录 | 高 |
| TOTP 加密密钥 | `TOTP_ENCRYPTION_KEY` | 已存储的 2FA secret 无法解密，2FA 用户被锁 | 高 |
| 数据库密码 | `DATABASE_PASSWORD` | 需同步更新 PG 和应用配置 | 中 |
| 邮箱 IP 哈希密钥 | `COMMUNITY_IP_HASH_SECRET` | 浏览去重计数重置（非安全风险） | 低 |

### 4.2 JWT 签名密钥轮换（SECRET_KEY）

项目内置密钥轮换支持：`JWT_PREVIOUS_SECRET_KEYS`（逗号分隔的历史密钥列表）。

**步骤**

1. **准备新密钥**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

2. **更新环境变量**（零停机）
   ```env
   # 把当前 SECRET_KEY 的值追加到历史列表
   JWT_PREVIOUS_SECRET_KEYS=<旧的SECRET_KEY值>
   # 设置新的 SECRET_KEY
   SECRET_KEY=<新生成的密钥>
   ```

3. **重启服务**（多 worker 逐个滚动重启）
   - 新 token 用新密钥签发
   - 旧 token 用 `JWT_PREVIOUS_SECRET_KEYS` 中的旧密钥校验（透明兼容）

4. **等待 access token 过期**（15 分钟）
   - 15 分钟后所有旧 access token 已过期
   - refresh token 轮换时也会用新密钥签发

5. **清理历史密钥**
   ```env
   # 确认无用户报告登录问题后，清空历史列表
   JWT_PREVIOUS_SECRET_KEYS=
   ```

6. **验证**
   - 确认新登录正常
   - 确认 15 分钟前的会话已自然过期
   - 检查日志无 token 校验异常

**回滚**：如新密钥有问题，把 `SECRET_KEY` 改回旧值，清空 `JWT_PREVIOUS_SECRET_KEYS`。

### 4.3 TOTP 加密密钥轮换（TOTP_ENCRYPTION_KEY）

> **风险提示**：TOTP_ENCRYPTION_KEY 轮换会导致已加密存储的 2FA secret 全部不可解密。
> 当前版本不支持双密钥解密窗口期。轮换前必须让所有 2FA 用户重新设置。

**步骤（需短暂维护窗口）**

1. **通知所有 2FA 用户**：将进行维护，2FA 需要重新设置
2. **生成新密钥**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
3. **更新环境变量**
   ```env
   TOTP_ENCRYPTION_KEY=<新生成的密钥>
   ```
4. **清除所有 2FA 记录**（数据库操作）
   ```sql
   -- 在维护窗口中执行
   TRUNCATE TABLE two_factor_auth;
   ```
5. **重启服务**
6. **通知用户重新设置 2FA**——用户登录后需重新走 setup → confirm 流程

**缓解方案（建议 1.1 实现）**：实现「双密钥解密」窗口期（类似 JWT_PREVIOUS_SECRET_KEYS）：新增 `TOTP_PREVIOUS_ENCRYPTION_KEYS` 配置；解密时先尝试当前密钥，失败后依次尝试历史密钥；轮换时：旧密钥加入历史列表 → 新密钥签发 → 后台任务用新密钥重新加密所有 secret → 清理历史列表。

### 4.4 数据库密码轮换（DATABASE_PASSWORD）

1. **在 PostgreSQL 中设置新密码**
   ```sql
   ALTER USER postgres WITH PASSWORD '<新密码>';
   ```
2. **更新应用环境变量**
   ```env
   DATABASE_PASSWORD=<新密码>
   ```
3. **重启服务**
4. **验证** `/readyz` 返回 200

### 4.5 轮换记录模板

每次轮换后填写：

```
日期：YYYY-MM-DD
操作人：
轮换密钥：
旧密钥指纹（前 8 位 sha256）：
新密钥指纹（前 8 位 sha256）：
验证结果：
备注：
```

---

## 5. 学习助手与可观测性安全（0.9.8 新增）

> 新增范围：Auxilio 学习助手（LLM）、API 调用埋点中间件、GitHub OAuth 登录、RBAC 默认管理员。
> 既有 §1–§4 安全条款（JWT 签发校验 / 密码哈希 / 黑名单 / RBAC 依赖 / 限流 / 密钥轮换）继续有效，本节为其补充，不替代。

### 5.1 Auxilio 学习助手 LLM 可选配置与安全降级

Auxilio 是面向**已登录用户**的学习助手，提供 SSE 流式对话与 Skills 工具调用（代码：`app/api/v1/auxilio.py`、`app/services/auxilio_agent.py`）。LLM 能力**完全可选，默认关闭**。

配置项（`app/core/config.py`）：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `none` | `openai` / `anthropic` / `none`；`none` = 不发起任何外部 LLM 请求 |
| `LLM_API_KEY` | 空 | 仅存于 `.env`，绝不落库 / 日志 / 前端 |
| `LLM_BASE_URL` | 空 | OpenAI 兼容网关（DeepSeek / 通义 / Kimi / 本地 vLLM） |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名 |
| `LLM_TIMEOUT` | `60` | 单次调用超时（秒），透传 httpx |
| `LLM_MAX_TOKENS` | `1024` | 单轮最大生成 token，透传请求体 |
| `LLM_DAILY_BUDGET` | `200` | 单用户每日 LLM 调用预算（0 = 不限制） |

安全降级（核心不变量）：

- `LLM_PROVIDER=none`（默认）或 `LLM_API_KEY` 缺失时，`llm_client.check_enabled()` 在 `run_chat` 入口抛 `LLMConfigError`，**直接走规则模式**：仅基于本地 `analyze_learning_profile` 返回薄弱知识点与资源推荐摘要，**不发起任何外部 HTTP 请求**。
- 即便全局未配置，登录用户也可在「API 调用统计」模块自行接入个人 API Key（见 5.2）；用户级配置优先级高于全局 `.env`。
- 系统提示词明确禁止编造数字、要求工具返回真实数据；工具结果视为用户生成内容（UGC），仅作参考。
- 所有 Auxilio 接口均经 `get_current_active_user` 鉴权；未登录不可调用（规则模式亦需登录）。
- `LLM_DAILY_BUDGET` 已在配置中定义，但当前代码中未发现基于该值的调用拦截逻辑（[待填写]：预算强制是否已在 0.9.8 接入待确认）。

### 5.2 用户级 LLM 配置（llm_configs）与密钥安全

用户可存储自有 LLM 配置于 `llm_configs` 表（`app/models/llm_config.py`，迁移 `d3e4f5a6b7c8`）：

- `api_key_encrypted`（最长 500 字符）以加密形式落库，读取经 `app.core.totp_encryption.decrypt_secret` 解密；**明文 Key 永不返回客户端、不写日志**。
- 该密钥仅用于发起该用户本人的模型调用，不用于后端聚合计费或其他用途。
- `llm_configs` 以 `user_id` 为主键，属应用数据（非凭证表），但含敏感密钥材料，须按 PII / 密钥同等标准保护。

### 5.3 api_usage 埋点中间件隐私边界

`app/middleware/api_usage.py` 为纯 ASGI 中间件，对每个 HTTP 请求异步写入 `api_call_logs`（`asyncio.create_task` fire-and-forget，失败静默、绝不阻断响应）。

隐私边界（强制）：

- **仅记录匿名调用计数**：落库字段为 `endpoint / method / status / latency_ms / created_at`，`user_id` 恒为 `NULL`——中间件不解析、不存储任何用户身份。
- **不记录请求体 / 响应体 / 查询参数 / Header / 客户端 IP**：无 PII、无令牌、无业务数据写入 `api_call_logs`。
- 端点路径归一化（`/api/v1/tools/exam/123` → `/api/v1/tools/exam/{id}`），既避免按资源 ID 炸开统计维度，也避免把具体资源 ID 落库。
- 跳过自身与运维端点：`/health`、`/readyz`、`/docs`、`/openapi.json`、`/workbench/stats/api-usage`，避免自指噪声。
- 与 §2.3 一致：观测埋点不得引入 PII；异常 / 结构化日志同样禁止记录密码、token、连接口令与原始校验输入。

> `api_call_logs`（匿名流量埋点）与 `llm_usage_logs`（按用户记录 token 消耗，见 5.2 对应迁移）用途不同：后者经 `get_current_active_user` 关联用户，属用量计量；前者为纯匿名流量统计。

### 5.4 GitHub OAuth 现状

GitHub OAuth 登录已实现（`app/api/v1/auth.py` 的 `/oauth/github`、`/oauth/github/callback`，`app/services/oauth_service.py`），用户标识落 `users.github_id`。

- **默认未启用**：`oauth_service.authorization_url()` 在 `GITHUB_CLIENT_ID` 未配置时返回 `None`，入口直接返回 `OAUTH_NOT_CONFIGURED`（400）。
- 启用需同时配置 `GITHUB_CLIENT_ID`、`GITHUB_CLIENT_SECRET`（可选 `GITHUB_CALLBACK_URL`，默认 `{SITE_URL}/api/auth/oauth/github/callback`）。
- 回调流程：校验 `state` → 换 token → `login_with_github` 登录 / 注册，与既有 JWT 体系一致。
- OAuth 登录同样受 §1 RBAC 与 §3 限流约束，不引入额外信任边界。

### 5.5 RBAC 与默认管理员

- 权限模型见 §1.2 `require_permission(resource, action)`；权限 / 角色由 `app/services/rbac_seed_data.py` 定义，经 `resource:action` 唯一约束登记。
- 启动任务 `rbac_seed`（priority 20，critical=True）在首次启动创建默认权限、角色与**默认管理员账号**（`ADMIN_USERNAME` / `ADMIN_EMAIL`，密码 `ADMIN_PASSWORD`，仅首次创建且永不写日志）；多 worker 经 PostgreSQL advisory lock 串行化，失败拒绝启动。
- 管理员账号属高权限主体，其创建 / 禁用受后端管理员保护规则（SELF_DISABLE / ROOT_PROTECTED / FORBIDDEN / LAST_ADMIN / NO_CHANGE）约束，相关密钥见 §4 密钥清单。
