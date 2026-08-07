# BackDoc-02-Sec：安全与防护（鉴权 / 异常 / 限流）

> 文档定位：**后端**的安全与防护权威文档（reference）
> 受众：安全审计人员 / 后端开发工程师 / 运维 / 权限设计者
> Source of truth：**后端**的鉴权基础设施、异常处理契约、请求限流配置
> 关联：架构见 [BackDoc-01-Arch.md](BackDoc-01-Arch.md)；基础设施见 [BackDoc-Infra.md](BackDoc-Infra.md)；编码规范见 [BackDoc-Conv.md](BackDoc-Conv.md)；前端 BFF 层安全与 UI 路由保护见 [FrontDoc-02-Sec.md](../../CS-Web-Frontend/tools/docs/FrontDoc-02-Sec.md)
> 最后更新：2026-08-05（统一 BackDoc 命名）
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
