# BackDoc-02-Sec：后端安全与防护（鉴权 / 异常 / 限流 / 密钥）

> 更新人：3yearsZ
> 更新日：2026-08-20
> 版本：1.0.1（版本基线对齐 1.0.1；含 0.9.8 LLM/api_usage/GitHub OAuth/RBAC 增补）
> Diátaxis：R（Reference · 规范参考 · 后端运行时安全唯一权威）
> 适用读者：安全审计人员、后端开发工程师、运维部署者、RBAC 权限设计者
> 变更触发：`app/core/security.py` 签名变更 / `.env` 安全配置项增删 / 限流策略调参 / 新增 `require_permission` 资源点 / 密钥轮换流程修改
>
> **SSOT（唯一权威）声明**：本文档是 FztbuCS 后端运行时安全机制的**唯一权威输入**。所有约束 MUST 在代码、配置、CI 门禁中落地；正文内容与实现不一致时，以本节约束为准并立即修复。前端 BFF 层安全（Origin 校验/UI 路由兜底/Next.js 安全头）请跳转 [FrontDoc-02-Sec.md](../../../CS-Web-Frontend/tools/docs/FrontDoc-02-Sec.md)，不在本文档范围。
>
> **关联索引**：架构总览 → [BackDoc-01-Arch.md](BackDoc-01-Arch.md)；工程约定 → [BackDoc-03-Conv.md](BackDoc-03-Conv.md)；深层威胁模型 → [CS-Mobile/tools/docs/arch/安全设计.md](../../../CS-Mobile/tools/docs/arch/安全设计.md) G5 STRIDE 15 条威胁与缓解映射

---

## 0. 文档速览：约束密度总表

| 章节 | 主题 | MUST 条数 | MUST NOT 条数 | SHOULD 条数 | MAY 条数 | 关键代码入口 |
|------|------|-----------|--------------|------------|----------|-------------|
| §1 | 鉴权与安全基础设施 | 10 | 6 | 4 | 2 | `app/core/security.py`、`security_blacklist.py`、`middleware/rbac.py` |
| §2 | 异常处理契约 | 7 | 5 | 3 | 1 | `app/core/exceptions/`、`error_codes.py` |
| §3 | 请求限流 | 5 | 4 | 3 | 2 | `app/core/rate_limit/`、`middleware/rate_limit.py` |
| §4 | 密钥与凭证管理 | 9 | 7 | 5 | 3 | `.env`、`app/core/config.py`、Alembic 迁移链 |
| §5 | 扩展功能安全（LLM/OAuth/埋点） | 8 | 6 | 4 | 2 | `app/services/auxilio_agent.py`、`middleware/api_usage.py`、`services/oauth_service.py` |
| §6 | — | **39（合计）** | **28（合计）** | **19（合计）** | **10（合计）** | — |

---

## 1. 鉴权与安全基础设施

### 1.1 概述（一句话定位）

后端签发并校验 Bearer JWT 双 token，基于 bcrypt 完成密码哈希，通过 Redis + 进程内存双层黑名单实现 access 撤销，使用 `require_permission(resource, action)` 依赖强制 RBAC0 授权。所有业务 API MUST 经由 `get_current_user` 注入当前用户上下文。

### 1.2 接口与代码入口清单

| 符号 / 配置项 | 签名 / 默认值 | 用途 |
|---|---|---|
| `create_access_token` | `create_access_token(data) -> (token, jti, exp)` | 签发 access JWT，自动注入 `jti/iss/aud/iat/token_type` |
| `verify_token` | `verify_token(token) -> dict \| None` | 校验签名、issuer、audience、`token_type=access`、`exp` |
| `async_get_password_hash` | `await async_get_password_hash(password)` | 在线程池执行 bcrypt，不阻塞事件循环 |
| `async_verify_password` | `await async_verify_password(raw, hashed)` | 在线程池校验 bcrypt，恒定时间防时序攻击 |
| `get_current_user` | FastAPI dependency | 解析 token → 回查用户激活态 → 回查 jti 黑名单 → 返回 User |
| `require_permission` | `require_permission(resource, action)` | 构造细粒度 RBAC0 依赖，与用户-角色-权限表三表联查 |
| `SECRET_KEY` | 环境变量，长度 ≥ 32 字节 | JWT HS256 签名密钥（§4 轮换） |
| `JWT_PREVIOUS_SECRET_KEYS` | 空字符串（逗号分隔历史列表） | 透明兼容旧 token 的轮换窗口期（§4.2） |
| `JWT_ISSUER` / `JWT_AUDIENCE` | 字符串 | 签发/校验一致性校验；不一致直接拒绝 |
| `JWT_ACCEPT_LEGACY_TOKENS` | `False`（默认关） | 仅迁移窗口临时开启； MUST NOT 长期保留 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | access 短时效； MUST NOT 超过 60 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | refresh 长时效； MUST NOT 超过 30 |
| `TOKEN_BLACKLIST_FALLBACK` | `closed`（fail-closed 安全优先） | Redis 不可用时的行为；`open` 仅开发调试可用 |
| `REQUIRE_REDIS_FOR_SECURITY` | `True`（生产强制） | 多 worker 下撤销一致性的硬开关 |

### 1.3 约束（RFC2119 分层）

**MUST（铁律红线，违反即安全漏洞）：**
1. 新签发的 JWT **MUST** 携带 `iss`、`aud`、`iat`、`jti`、`token_type=access`、`exp` 六项声明；缺少任意一项，校验层直接拒绝。
2. 所有 bcrypt 哈希/校验调用 **MUST** 走 `async_get_password_hash` / `async_verify_password` 线程池封装；禁止在 async 协程内直接调用阻塞 bcrypt。
3. bcrypt 输入 **MUST** 限制 ≤ 72 UTF-8 字节；超过部分截断并记录警告日志。
4. `get_current_user` **MUST** 依次校验：token 签名有效 → 用户 `is_active=True` → 用户任一角色 `is_active=True` → jti 不在黑名单；任何一步失败直接 401。
5. 多 worker 部署且要求即时撤销一致性时，**MUST** 开启 `REQUIRE_REDIS_FOR_SECURITY=True`：启动期强制校验 `REDIS_URL`、强制 `TOKEN_BLACKLIST_FALLBACK=closed`；Redis 不可用则启动拒绝（fail-closed）。
6. `inactive` 用户 **MUST NOT** 授予任何访问权限；`inactive` 角色 **MUST NOT** 参与权限计算，等价于用户无此角色。
7. RBAC0 **MUST** 在服务端 enforce，即 `require_permission` 以 FastAPI dependency 在路由层硬绑定；前端 UI 隐藏按钮仅作 UX 兜底，不能替代后端 enforce。
8. 新增权限资源点 **MUST** 同步更新 `rbac_seed_data.py` 并加 `resource:action` 数据库唯一约束；未登记的资源点在 CR 阶段必须打回。
9. 密码校验失败与成功的响应时间差 **MUST** 被 bcrypt 恒定时间比较与 2FA 预认证 token 掩盖，避免时序侧信道。
10. JWT 签名算法 **MUST** 固定为 HS256（显式声明），**MUST NOT** 接受 `alg=none` 或外部指定的弱算法头。

**MUST NOT（禁止事项，违反即安全漏洞）：**
1. **MUST NOT** 硬编码 `SECRET_KEY`、`TOTP_ENCRYPTION_KEY`、`DATABASE_PASSWORD` 到代码或 Git 仓库；仅允许从 `.env` 注入。
2. **MUST NOT** 在日志、异常响应体、错误消息、埋点中打印 access/refresh token、密码明文、bcrypt 哈希值、TOTP secret。
3. **MUST NOT** 通过 URL query string 传递 token、密码、TOTP 验证码；必须走 Authorization header 或 POST JSON body。
4. **MUST NOT** 让 `JWT_ACCEPT_LEGACY_TOKENS=True` 在生产停留超过 1 个 access 生命周期 × 2（即 30 分钟窗口）。
5. **MUST NOT** 允许 `user_id`、`is_admin`、`role` 等身份字段从客户端请求参数直接注入；必须由 `get_current_user` 从 token 反查，不可信任何客户端声明。
6. **MUST NOT** 把 `current_user.is_active` 检查放到单个业务路由；必须在依赖注入层统一完成，避免路由遗漏。

**SHOULD（建议事项，偏离需在 CR 说明理由）：**
1. access 有效期 **SHOULD** 维持 15 分钟；确需延长的场景 **SHOULD NOT** 超过 30 分钟，并补充更严的撤销机制。
2. refresh 轮换策略 **SHOULD** 每次 `/auth/refresh` 调用都返回一对全新双 token（轮换 + 复用检测，旧 refresh 立即失效），避免 token 无限重放窗口。
3. 撤销黑名单 **SHOULD** 采用双层回查：先 Redis 再进程内存；Redis 恢复后，进程内存中降级窗口内拉黑的 jti **SHOULD** 继续有效，避免撤销回滚。
4. 管理员创建 `ADMIN_PASSWORD` **SHOULD** 启动后 24 小时内由首登管理员立即修改，并在日志中记录首次使用的 trace。

**MAY（可选配置，不影响安全基线）：**
1. 单 worker 且用户规模 < 50 的开发测试部署，**MAY** 临时关闭 `REQUIRE_REDIS_FOR_SECURITY` 以简化依赖；但 MUST 同步将 `TOKEN_BLACKLIST_FALLBACK` 设为 `closed`，降级到进程内存黑名单。
2. 特定场景（如 SSO 迁移窗口）**MAY** 临时开启 `JWT_ACCEPT_LEGACY_TOKENS=True`，但 MUST 在迁移完成后立即通过 CI 配置检查打回 `False`。

### 1.4 自检 CheckList

- [ ] 新增/修改签发逻辑时，已同步校验 §1.2 中 6 项 JWT 声明是否齐全
- [ ] 任何涉及 password / token 的代码变更，已 grep 确认无 `print()` / 日志明文输出
- [ ] `require_permission` 新增资源点，已同步登记 `rbac_seed_data.py` + Alembic seed 数据
- [ ] 配置项变更后，`.env.example` 模板与 `config.py` 默认值保持双写一致
- [ ] 本节 10 条 MUST 约束，在 `tools/tests/core/test_security.py` / `test_rbac_permissions.py` 中有对应反向测试用例（违反 MUST 应断言失败）

---

## 2. 异常处理契约

### 2.1 概述（一句话定位）

业务失败统一以 `BaseAppException` 子类表达，由全局 handler 映射为稳定 `ClientError` 响应体；最外层 `ExceptionHandlerMiddleware` 兜底路由层外异常。`ErrorCode` 注册表是客户端错误码的单一事实源（SSOT）。

### 2.2 接口与代码入口清单

| 符号 | 用途 | 关联文件 |
|---|---|---|
| `BaseAppException` | 业务异常基类，承载 `status_code/error_code/message/details/security_info` | `app/core/exceptions/base_exceptions.py` |
| `ErrorCode` | 客户端错误码枚举与唯一注册入口；命名空间 = `{领域}_{7位数字}` | `app/core/exceptions/error_codes.py`（例如 `A020003` = 重复报名冲突） |
| `setup_exception_handlers(app)` | 注册业务异常、Pydantic 校验、HTTP 4xx/5xx、DB 异常、兜底 handler | `app/core/exceptions/handlers.py` |
| `ExceptionHandlerMiddleware` | ASGI 中间件，捕获路由层外异常（Depends 执行前 / 响应序列化时），按状态映射统一 JSON | `app/core/exceptions/middleware.py` |
| `ExceptionLogRepo` | 独立 DB 会话异步持久化异常日志；失败静默写 app logger，不影响 HTTP 响应 | `app/repositories/exception_log_repo.py` |
| `/api/v1/exceptions` | 超级用户查询异常日志端点（RBAC protect）；契约见 `app/api/v1/exceptions.py` | 仅 admin 可访问 |

### 2.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. 路由层业务异常 **MUST** 继承 `BaseAppException` 并引用 `ErrorCode.*` 枚举值；禁止裸字符串 error_code。
2. 异常中间件短路响应 **MUST** 使用 `JSONResponse` 返回；**MUST NOT** 抛出 `HTTPException`（绕过统一响应体）。
3. Pydantic 校验错误 **MUST** 移除原始 `input` 字段后再输出，避免密码、token、TOTP 验证码在 422 响应中回显或落日志。
4. 数据库异常（IntegrityError / OperationalError 等）**MUST** 仅返回稳定通用消息和错误码（如 `D050001 数据库操作失败`）；**MUST NOT** 向客户端暴露驱动异常原文、SQL 语句、唯一约束名。
5. 异常日志持久化 **MUST** 使用独立数据库会话（`exception_db: Session`），不共享业务事务；写入失败 MUST 降级为应用日志记录，**MUST NOT** 覆盖或修改原始 HTTP 响应状态码。
6. 日志 **MUST** 只记录归一化请求路径（`/api/v1/users/{id}` 而非带参数完整 URL），避免 token、手机号、邮箱泄露到 access log。
7. `ErrorCode` **MUST** 全局唯一（`{字母域前缀}_{7位数字}`）；新增 MUST 在 CR 阶段经 `error_codes.py` grep 查重。

**MUST NOT（禁止事项）：**
1. **MUST NOT** 在路由、service 层裸 `try/except: pass` 或空 catch 静默吞错；异常要么携带上下文向上抛，要么显式记录 + 转 `BaseAppException`。
2. **MUST NOT** 在异常响应体、异常日志中包含 `.env` 密钥、DB 连接串内部 IP、内部路径堆栈（traceback 仅 DEBUG 模式输出，生产 MUST 关闭）。
3. **MUST NOT** 允许路由函数返回非标准格式的自定义错误 JSON；任何错误 MUST 走统一 handler。
4. **MUST NOT** 把 5xx 业务失败降级为 200 成功响应带 `success=false`；状态码语义 MUST 与 HTTP 规范一致。
5. **MUST NOT** 在 Alembic 迁移外调用 `Base.metadata.create_all()` 建表；异常日志表结构 MUST 经 Alembic 迁移维护。

**SHOULD（建议事项）：**
1. **SHOULD** 把异常分类映射到可重试标记：如网络抖动/限流返回 `retryable=true`，参数校验/权限不足返回 `retryable=false`，便于客户端统一退避策略。
2. **SHOULD** 为敏感操作（登录、管理员操作、密钥变更）的异常增加安全上下文 `security_details` 字段（仅 superuser 可见的扩展详情），普通客户端视图 MUST 隐藏此字段。
3. **SHOULD** 异常日志写入速率 **SHOULD** 被独立限流（如 100/分钟/实例），避免错误风暴拖垮 DB。

**MAY（可选配置）：**
1. 开发调试期 **MAY** 临时开启 `DEBUG=true` 让异常响应体携带 traceback，但 MUST 通过 `api_docs_enabled` 跟随 DEBUG 开关联动，生产 MUST 自动关闭。

### 2.4 自检 CheckList

- [ ] 新增业务异常类时，已在 `base_exceptions.py` 定义 + `error_codes.py` 注册唯一编号 + `__init__.py` 导出
- [ ] 所有 `try/except` 已检查，无空 catch；异常路径均携带上下文（路径、入参类型、用户 id）
- [ ] §2.3 5 条 MUST NOT 约束，在 `tools/tests/core/test_exception_handlers.py` 中反向覆盖（如 422 响应不含 `input`、DB 异常不含 SQL）
- [ ] 异常 handler 数量变动后，已确认 `setup_exception_handlers` 注册顺序正确（具体异常 handler 优先于兜底 handler）
- [ ] 统一错误响应体字段（`success/error_code/message/status_code/timestamp`）与 `openapi.baseline.json` 契约 `ClientError` schema 保持一致

---

## 3. 请求限流

### 3.1 概述（一句话定位）

限流以「全局窗口（所有请求） + 认证窗口（登录/注册/refresh）」双层执行；后端优先 Redis 共享计数，未配置或故障时降级为进程内存计数。客户端 IP 仅从可信反代网段的转发头解析，避免伪造 IP 绕过限流。

### 3.2 接口与配置清单

| 符号 / 配置项 | 默认值 | 用途 |
|---|---|---|
| `get_client_ip(request, trusted_proxies=()) -> str` | — | 从右向左跳过可信代理链，取第一个不可信来源 IP |
| `RateLimitMiddleware` | `calls=100, period=60`（全局默认） | 全局限流中间件；可按 `limit_paths` 指定子集 |
| `AuthRateLimitMiddleware` | `calls=5, period=60`（认证严格默认） | 认证端点限流：`/auth/login-*`、`/auth/register`、`/auth/send-code`、`/auth/refresh` |
| `RATE_LIMIT_CALLS / RATE_LIMIT_PERIOD` | 100 / 60（秒） | 全局窗口环境变量覆写 |
| `AUTH_RATE_LIMIT_CALLS / AUTH_RATE_LIMIT_PERIOD` | 5 / 60（秒） | 认证窗口环境变量覆写 |
| `TRUSTED_PROXY_CIDRS` | 空元组 | 可信反向代理 CIDR；为空时直接使用 `request.client.host` |
| `REDIS_URL` | — | 限流共享后端；未配置时自动降级为进程内存 |
| 超限响应 | 429 JSON + `Retry-After` header | 统一返回 `C429001 请求过于频繁，请稍后重试`；中间件 **不** 抛 HTTPException |

### 3.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. 客户端 IP 解析 **MUST** 仅在直连来源落入 `TRUSTED_PROXY_CIDRS` 可信网段时，才读取 `X-Forwarded-For` / `X-Real-IP`；不可信来源的转发头 **MUST** 丢弃，直接用 `request.client.host`。
2. 可信代理链解析 **MUST** 从右向左跳过 `TRUSTED_PROXY_CIDRS` 内连续条目，取第一个不可信地址；禁止从左向右取（易被首跳伪造）。
3. 认证端点 **MUST** 叠加 `AuthRateLimitMiddleware`（默认 5/60s），其计数器 MUST 独立于全局限流，不被全局 100/60s 稀释防爆破效果。
4. 超限响应 **MUST** 返回 `429` 状态码 + `Retry-After` header（秒数）+ 统一错误码 `C429001`；**MUST NOT** 用 200 携带失败信息。
5. Redis 是否可用 **MUST NOT** 成为启动硬依赖；Redis 连接超时 MUST 自动降级到进程内存计数，日志记录一次降级告警，不阻塞服务启动。

**MUST NOT（禁止事项）：**
1. **MUST NOT** 把 `TRUSTED_PROXY_CIDRS` 配置为 `0.0.0.0/0` 或过宽公网网段；该错误等价于禁用 IP 伪造防护，必须在 CR + CI 配置检查阶段阻断。
2. **MUST NOT** 允许限流键只取 user_id 不取 client_ip（未登录场景无法按 user_id 限流；必须用 IP 作为匿名场景兜底键）。
3. **MUST NOT** 对限流计数键使用可枚举的自增 ID 或预测值；必须使用 `{ip|user_id}_{窗口start_ts}` 归一化形式避免碰撞。
4. **MUST NOT** 让限流中间件抛出 `HTTPException`（绕过统一异常 handler）；必须直接返回 `JSONResponse(status_code=429)` 与 §2 响应格式一致。

**SHOULD（建议事项）：**
1. **SHOULD** 在反代层（C-06 Nginx/Caddy）额外叠加南北向 20 QPS 全局限流作为第一道防线，与后端中间件形成「反代 20 QPS + 后端 100/60s ≈ 1.67 QPS 折合」的分层防护。
2. **SHOULD** 对连续被限流 10 次以上的 IP 写入 WAF 临时黑名单（5 分钟），降低爆破面。
3. **SHOULD** 限流命中计数 MUST 定期上报 Prometheus metrics（`rate_limit_hit_total{type=global|auth}`），便于运营看板观察爆破尝试。

**MAY（可选配置）：**
1. 小规模内测部署（< 20 用户）**MAY** 临时调大 `RATE_LIMIT_CALLS` 方便联调，但 MUST 同步在 `AUTH_RATE_LIMIT_CALLS` 维持防爆破收紧，不能把认证窗口一起放宽。
2. 特定白名单 IP（如内部运维网段）**MAY** 叠加 `limit_paths` 排除机制跳过限流，但 MUST 在代码中以显式 CIDR 常量声明，禁止硬编码单个 IP。

### 3.4 自检 CheckList

- [ ] `TRUSTED_PROXY_CIDRS` 已按部署环境真实反代网段填写，grep 确认无 `0.0.0.0/0` 错误配置
- [ ] `tools/tests/middleware/test_rate_limit.py` 反向覆盖：普通限流 / 认证限流独立计数 / 不可信代理头被丢弃 / Redis 降级到内存 四类场景均有断言
- [ ] 429 响应体格式与 §2 统一错误响应一致（`success=false / error_code=C429001`）
- [ ] 新增端点被确认为认证相关后，已追加到 `AuthRateLimitMiddleware` 的路径清单
- [ ] 反代层 WAF 限流阈值与后端 `RATE_LIMIT_*` 配置已做交叉对账，避免「后端 100/60s 但反代直接 20 QPS 截断」的不一致

---

## 4. 密钥与凭证管理 + 轮换 Runbook

### 4.1 概述（一句话定位）

所有高敏凭证（JWT 签名密钥、TOTP 加密密钥、DB 密码、社区 IP 哈希密钥）仅存 `.env`（权限 0600），通过 compose 环境变量注入容器，禁止硬编码或打包进镜像。本节同时定义四类密钥的轮换 Runbook 与记录模板。

### 4.2 密钥清单与保护分级

| 密钥 | 环境变量 | 级别 | 轮换周期 | 泄露影响 | 代码入口 |
|------|----------|------|----------|----------|---------|
| JWT 签名密钥 | `SECRET_KEY` | L4 高敏（RFC2119 MUST 级） | ≤ 6 个月 或 疑似泄露立即 | 所有 access/refresh token 失效，用户需重登 | `app/core/security.py` create/verify |
| TOTP 加密密钥 | `TOTP_ENCRYPTION_KEY` | L4 高敏 | ≤ 6 个月 | 已存储 2FA secret 全部不可解密（当前无双密钥窗口） | `app/core/totp_encryption.py` |
| 数据库密码 | `DATABASE_PASSWORD` | L4 高敏 | ≤ 3 个月 | 后端不可连 DB，需同步 PG + compose | docker-compose + `app/core/config.py` |
| 社区 IP 哈希密钥 | `COMMUNITY_IP_HASH_SECRET` | L3 敏感 | ≤ 12 个月 | 匿名化 IP 可被反查；**fail-fast：缺失则启动拒绝** | `app/services/community_service.py` |
| 2FA 种子（单用户） | `two_factor_auths.secret_encrypted` | L3 敏感 | 随用户重设 | 单用户 2FA 被绕过 | 列级加密（AES-256-GCM + TOTP_ENCRYPTION_KEY） |
| Refresh token（单用户） | `refresh_tokens.token_hash` | L3 敏感 | 7 天自然过期 | 可冒充用户调用 API（7 天窗口内） | sha256 存库，不明文 |
| 第三方 OAuth 密钥 | `GITHUB_CLIENT_SECRET` / `SMTP_PASSWORD` | L4 高敏 | 第三方账号变更时立即 | 冒充 FztbuCS 发起 OAuth / 邮件 | `.env` 注入 + `app/services/oauth_service.py` |
| LLM API Key（全局/用户级） | `LLM_API_KEY`（全局）/ `llm_configs.api_key_encrypted`（用户级） | L4 高敏 | 用户主动撤销 | 第三方调用账单被盗刷；用户级密钥按 §5.2 列级加密 | `.env` + AES 列级加密 |

### 4.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. 所有 L4 级密钥 **MUST** 仅通过 `.env` 环境变量注入；**MUST NOT** 出现在 `Dockerfile` `ENV` 指令、Git 仓库、备份明文、CI log。
2. `.env` 文件权限 **MUST** 为 0600（仅 owner 可读）；部署脚本 MUST 校验此权限，错误则部署失败。
3. Docker 镜像构建 **MUST** 在 `.dockerignore` 中排除 `.env`；镜像层中 **MUST NOT** 包含任何密钥材料。
4. `SECRET_KEY`、`TOTP_ENCRYPTION_KEY`、`COMMUNITY_IP_HASH_SECRET` **MUST** 长度 ≥ 32 字节（使用 `secrets.token_urlsafe(48)` 生成）；启动期校验长度，不足则启动拒绝。
5. `COMMUNITY_IP_HASH_SECRET` **MUST** fail-fast：缺失直接拒绝启动；**MUST NOT** 回退到硬编码默认值（之前缺陷已修复并记录在变更日志）。
6. 轮换高敏密钥后 **MUST** 填写 §4.7 轮换记录模板，指纹（前 8 位 sha256）必须留存，便于事后审计对账。
7. 人员离职或密钥疑似泄露时 **MUST** 立即启动应急轮换，不受常规轮换周期限制。
8. 备份文件（PostgreSQL pg_dump）**MUST** 使用 openssl AES-256 加密后再离线存储；备份明文 **MUST NOT** 离开宿主机。
9. 用户自有 LLM API Key **MUST** 通过 `totp_encryption.encrypt_secret` 加密后再落 `llm_configs.api_key_encrypted` 列；明文 **MUST NOT** 返回客户端、不得出现在日志、不得出现在 API 响应。

**MUST NOT（禁止事项）：**
1. **MUST NOT** 把 `.env` 加入 Git；根级与子仓库 `.gitignore` 必须显式列出 `.env`、`.env.local`、`*.env.*`。
2. **MUST NOT** 通过 GitHub Actions / Jenkins log 输出环境变量；CI 密钥必须走 secrets manager 并 mask 输出。
3. **MUST NOT** 在部署文档、运行手册、邮件、即时消息中传递明文密钥；传递方式 MUST 使用一次性密钥分享工具并限制 24 小时过期。
4. **MUST NOT** 把 `SECRET_KEY` 同时用于 JWT 签名 + TOTP 加密 + 社区 IP 哈希；三者 MUST 使用独立密钥，避免一处密钥泄露击穿多道防线。
5. **MUST NOT** 在 `JWT_PREVIOUS_SECRET_KEYS` 中永久保留旧密钥；轮换窗口期（默认 30 分钟）结束后 MUST 立即清空列表。
6. **MUST NOT** 在容器内运行的应用日志中打印完整环境变量列表（`print(os.environ)`）；**MUST NOT** 在 DEBUG 端点暴露环境变量值。
7. **MUST NOT** 允许非管理员用户通过任何接口查询 `.env` 项或配置值；配置变更必须通过运维 SSH 通道完成。

**SHOULD（建议事项）：**
1. **SHOULD** 实现 TOTP 双密钥解密窗口期（类似 `JWT_PREVIOUS_SECRET_KEYS`）：新增 `TOTP_PREVIOUS_ENCRYPTION_KEYS` 配置，解密先试当前密钥再按顺序试历史密钥；缓解 §4.5 截断用户 2FA 的影响。
2. **SHOULD** 对 `.env` 变更引入「变更前备份 + 变更后 make check-config」的两步流程；`check-config` 脚本校验必填密钥存在且长度达标。
3. **SHOULD** DB 密码 **SHOULD** 与 JWT/TOTP 密钥错峰轮换（例如 DB 每月月中、JWT 每月月底），避免一次全换导致的故障面重叠。
4. **SHOULD** 把 `DATABASE_PASSWORD` 变更纳入 db migrations 流水线：先改 PG 用户口令 → 滚动重启容器 → 校验 `/readyz`；三步可执行脚本封装。
5. **SHOULD** 轮换 JWT 密钥后，主动推送系统通知「安全维护完成，若会话失效请重新登录」，降低用户困惑。

**MAY（可选配置）：**
1. **MAY** 接入 HashiCorp Vault / Infisical 等密钥管理服务替代 `.env`，但本地开发部署路径 **MAY** 保留 `.env.example` → `.env` 流程，避免小团队运维复杂度。
2. 多环境部署（prod / uat / int）**MAY** 使用不同前缀的密钥集，但 **MUST** 保证各环境密钥不互通（密钥指纹必须不同）。
3. 用户级 LLM 密钥轮换 **MAY** 提供「在个人中心点击撤销并重新录入」自助流程，无需运维介入。

### 4.4 JWT 签名密钥轮换（SECRET_KEY，零停机）

**步骤：**
1. 生成新密钥：`python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. 更新 `.env`：把当前 `SECRET_KEY` 追加到 `JWT_PREVIOUS_SECRET_KEYS`，并将新值写入 `SECRET_KEY`
3. 多 worker 逐个滚动重启（验证兼容期生效）
4. 等待 ≥ 2 × `ACCESS_TOKEN_EXPIRE_MINUTES`（默认 30 分钟）确认旧 access 已全部过期
5. 清空 `JWT_PREVIOUS_SECRET_KEYS` 后再次滚动重启，关闭兼容窗口
6. 验证：新登录正常 + 15 分钟前会话自然过期 + 日志无 token 校验异常

**回滚：** 如新密钥异常，把 `SECRET_KEY` 改回旧值、清空历史列表，立即重启。

### 4.5 TOTP 加密密钥轮换（TOTP_ENCRYPTION_KEY，需维护窗口）

> ⚠️ **风险提示**：当前版本无 TOTP 双密钥解密窗口，轮换 MUST 提前通知所有 2FA 用户重设。

**步骤：**
1. 提前 24 小时通知所有 2FA 用户：将进行安全维护，需要重新走 2FA setup → confirm 流程
2. 生成新密钥 + 更新 `.env` `TOTP_ENCRYPTION_KEY`
3. 在维护窗口执行：`TRUNCATE TABLE two_factor_auth;`（DBA 操作）
4. 重启服务
5. 通知用户登录后重设 2FA

### 4.6 DB 密码轮换（DATABASE_PASSWORD）

**步骤：**
1.  PostgreSQL 执行：`ALTER USER <业务用户> WITH PASSWORD '<新密码>';`
2.  更新 compose `.env` `DATABASE_PASSWORD`
3.  滚动重启后端容器
4.  验证：`/readyz` 返回 200，连续业务接口（登录/公告列表）调用无错

### 4.7 轮换记录模板（每次轮换 MUST 填写）

```yaml
日期: YYYY-MM-DD
操作人: <运维或安全负责人>
轮换密钥: <SECRET_KEY / TOTP_ENCRYPTION_KEY / DATABASE_PASSWORD / COMMUNITY_IP_HASH_SECRET>
旧密钥指纹(sha256前8位): <8 hex>
新密钥指纹(sha256前8位): <8 hex>
验证结果: <新登录正常 / 无 2FA 用户报障 / readyz 200 连续 3 次>
备注: <是否使用兼容窗口 / 维护窗口时长 / 特殊回滚点>
```

### 4.8 自检 CheckList

- [ ] §4.3 9 条 MUST 约束，在 `tools/tests/` 中有对应的 fail-fast 启动测试（密钥缺失/过短时启动拒绝）
- [ ] `.gitignore` 已 grep 确认 `.env` / `.env.local` / `*.env.*` 全部被排除
- [ ] 每类 L4 密钥指纹已登记在运维笔记本；轮换后 4.7 模板已归档
- [ ] 新增高敏环境变量后，已同步到根级 + 后端 `.env.example` 双模板
- [ ] 轮换脚本（4.4-4.6）均在 UAT 环境完整演练过一次，且有回滚演练记录

---

## 5. 扩展功能安全（LLM / api_usage 埋点 / GitHub OAuth / RBAC 初始化）

### 5.1 概述（一句话定位）

0.9.8 版本新增的 Auxilio LLM 学习助手、`api_usage` 匿名埋点中间件、GitHub OAuth 登录、RBAC 启动种子四项扩展功能，均须在不扩大既有信任边界的前提下安全运行；本节定义其特有约束与降级策略。

### 5.2 接口与配置清单

| 模块 | 配置项 | 默认值 | 安全基线 |
|------|--------|--------|---------|
| Auxilio LLM | `LLM_PROVIDER` | `none`（默认完全关闭） | `none` 时只走本地规则模式，不发起任何外部 HTTP |
| Auxilio LLM | `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_TIMEOUT` / `LLM_MAX_TOKENS` | 空 / 空 / `gpt-4o-mini` / 60s / 1024 | 全局 `.env` 注入，用户级配置优先级更高（见 §5.2.2） |
| Auxilio LLM | `LLM_DAILY_BUDGET` | 200（次/用户/天） | 单用户预算；0 表示不限制（待 W-2 落地确认） |
| 用户级 LLM Key | `llm_configs.api_key_encrypted` | 加密列 | AES-GCM 加密，仅用户本人调用 decrypt |
| api_usage 埋点 | `app/middleware/api_usage.py` 字段 | `endpoint/method/status/latency_ms/created_at` | user_id 恒为 NULL，完全匿名 |
| GitHub OAuth | `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | 空（默认未启用） | 缺失时入口直接返回 `OAUTH_NOT_CONFIGURED` 400 |
| RBAC 初始化 | `rbac_seed` startup 任务 | priority=20, critical=True | PostgreSQL advisory lock 单实例执行，失败直接拒绝启动 |

### 5.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. 当 `LLM_PROVIDER=none` 或全局 `LLM_API_KEY` 缺失且用户无自有 Key 时，Auxilio 对话入口 **MUST** 直接抛出 `LLMConfigError` 并降级为本地规则模式，**MUST NOT** 发起任何外部 HTTP 调用。
2. 所有 Auxilio 接口 **MUST** 经 `get_current_active_user` 鉴权；未登录不可调用，即便本地规则模式也 MUST 登录（防匿名滥用 LLM 预算）。
3. 用户级 LLM API Key **MUST** 经 `totp_encryption.encrypt_secret` 加密落 `api_key_encrypted`；明文 **MUST NOT** 返回 `/users/me`、不得写入 `llm_usage_logs`、不得出现在任何日志。
4. `api_usage` 埋点 **MUST** 仅记录 `endpoint/method/status/latency_ms/created_at` 五字段；`user_id` 恒为 NULL、**MUST NOT** 记录请求体/响应体/查询参数/Header/IP，并 MUST 归一化路径（`/api/v1/tools/exam/{id}`）。
5. `api_usage` 埋点 **MUST** 以 `asyncio.create_task` fire-and-forget 执行；失败静默，**MUST NOT** 阻塞或影响正常 HTTP 响应。
6. GitHub OAuth **MUST** 在 `GITHUB_CLIENT_ID` 缺失时返回 `OAUTH_NOT_CONFIGURED` 状态码 400；**MUST NOT** 暴露回调跳转链接或伪造 OAuth 入口。
7. OAuth 回调流程 **MUST** 校验 `state` 参数防止 CSRF；token 交换 **MUST** 在服务端完成，**MUST NOT** 交给客户端传 token。
8. RBAC 启动 seed **MUST** 通过 PostgreSQL advisory lock 保证多 worker 下仅一个实例创建默认管理员；关键步骤失败（DB 连不上 / advisory lock 取锁失败 / 密码为空） MUST 直接拒绝启动（critical=True）。

**MUST NOT（禁止事项）：**
1. **MUST NOT** 在 LLM prompt 中注入完整用户数据、会话历史中的其他用户消息、或完整数据库内容；**MUST NOT** 把 `SECRET_KEY`、`DATABASE_PASSWORD` 作为上下文或工具返回值喂给 LLM。
2. **MUST NOT** 让 LLM 工具调用具备写数据库、发邮件、调管理员接口的能力；工具调用集 MUST 严格限制为只读查询 + 本地代码分析。
3. **MUST NOT** 在 `api_call_logs` 中写入用户身份。若需要按用户维度做 LLM 用量统计，**MUST** 走独立的 `llm_usage_logs` 表（经 `get_current_active_user` 鉴权），两张表的字段与读写路径 **MUST NOT** 混合。
4. **MUST NOT** 允许 `ADMIN_PASSWORD` 通过任何 API 接口回显或修改；默认管理员创建 MUST 不在日志中打印密码明文。
5. **MUST NOT** 允许 OAuth 用户跳过邮箱密码登录体系直接创建管理员角色；OAuth 注册 MUST 默认为 `member` 角色，管理员升级走 RBAC 手工流程。
6. **MUST NOT** 把 GitHub OAuth 的 `state` 参数复用为 CSRF token 之外用途；每次 OAuth 跳转 MUST 生成一次性 `state` 并绑定到登录 session。

**SHOULD（建议事项）：**
1. 用户级 LLM Key **SHOULD** 支持「测试连接」按钮，加密前用一次最小请求验证有效性，避免把无效密钥加密落库。
2. LLM 全局 200 次/天预算 **SHOULD** 接入独立 Redis 计数窗口；超限 MUST 返回预算耗尽错误码，静默降级为规则模式。
3. GitHub OAuth **SHOULD** 审计日志 MUST 记录「谁在何时用 OAuth 登录成功/失败、从哪个 IP」，与邮箱密码登录的审计粒度一致。
4. RBAC 默认管理员账号 **SHOULD** 在首次启动后 72 小时内由首登管理员强制改密码；改密完成后 SHOULD 更新 `ADMIN_PASSWORD` 历史值标记为已过期。

**MAY（可选配置）：**
1. LLM 基础能力 **MAY** 关闭个人用户自接入 Key 的入口（部署侧决定），仅允许全局 `.env` 统一接入；该开关 MUST 通过配置项显式声明（`LLM_ALLOW_USER_KEY=true|false`）。
2. 小型部署 **MAY** 把 `api_usage` 匿名统计 endpoint 白名单范围缩小，只记核心业务（忽略内部工具端）。

### 5.4 自检 CheckList

- [ ] LLM 工具调用集已审计：全部只读，无 DB 写 / 邮件发 / 管理员操作
- [ ] `api_usage` 埋点字段已 grep 确认：user_id 恒为 NULL；无 body/header/param 记录写入代码路径
- [ ] GitHub OAuth state CSRF 校验 + 服务端换 token：在 `tools/tests/integration/test_oauth.py` 有反向用例（缺失 state 应失败）
- [ ] RBAC seed 在并发 10 实例启动测试下（`pg_try_advisory_xact_lock`）仅 1 个成功，其余等待且不重复创建默认管理员
- [ ] 默认管理员创建流程：启动日志 grep 确认未打印 `ADMIN_PASSWORD` 明文

---

## 6. 变更门禁 + Pre-commit 必查清单（Reference 型文档强制尾章）

> 本章对应《模块契约文档》同款 pre-commit checklist。每次提交涉及安全的代码/配置变更前，提交人 MUST 逐项自查并在 PR 描述中打钩；CR 审核人 MUST 核对本清单并在未打钩时打回。

### §6.1 通用门禁（所有安全变更适用）

- [ ] 变更是否影响 §1-§5 中任一 MUST/MUST NOT 约束？若是，本节约束文字 MUST 已同步更新
- [ ] 新增/修改接口的 OpenAPI schema 是否已走 `make contract-baseline` 更新基线，`make contract-check` 通过
- [ ] `.env` 配置项变更是否已同步更新：根级 `.env.example` + 后端 `CS-Web-Backend/.env.example` + `app/core/config.py` 默认值 三处对齐
- [ ] 版本号、变更日期是否已在本文档 6 行元数据头同步更新
- [ ] `gen_doc_facts.py` 派生事实同步（`make gen-doc-facts`）：Alembic head / 版本一致性 / 模块契约对齐 / 测试存在 四项无漂移

### §6.2 鉴权变更门禁（§1 相关）

- [ ] 签发/校验逻辑变更后，`tools/tests/core/test_security.py` 全量通过，并新增了对应反向用例（违反 MUST 应失败）
- [ ] 新 token 声明是否与 `JWT_ISSUER / JWT_AUDIENCE / token_type` 兼容性校验一致
- [ ] 密码哈希调用是否全部走线程池封装，无阻塞 async 事件循环
- [ ] RBAC 资源点变更是否已同步更新 `rbac_seed_data.py` + Alembic seed 数据 + 唯一约束

### §6.3 异常契约变更门禁（§2 相关）

- [ ] 新增异常类是否三要素齐全：基类继承 + `ErrorCode` 唯一注册 + `__init__.py` 导出
- [ ] 客户端错误码在前端 `FrontDoc-02-Sec.md` 错误码映射表是否已同步更新（如涉及 UI 提示文案）
- [ ] Pydantic 校验错误回显 `input` 的过滤逻辑是否仍然生效，测试反向覆盖
- [ ] 统一响应体 `ClientError` schema 是否仍与 `openapi.baseline.json` 一致

### §6.4 限流配置变更门禁（§3 相关）

- [ ] `TRUSTED_PROXY_CIDRS` 变更是否已和实际反代网段对账，避免过宽/过窄
- [ ] 认证限流窗口调大时，防爆破效果是否仍然满足「5 次失败锁定/告警」的底线
- [ ] 反代层南北向限流与后端限流的阈值分层是否仍然合理（两层不相互抵消）

### §6.5 密钥管理门禁（§4 相关）

- [ ] 高敏密钥提交前，Git 历史 `git log -p -S "SECRET_KEY"` 检查：确认无明文提交
- [ ] `.dockerignore` / `.gitignore` 未遗漏密钥类文件
- [ ] 轮换后 4.7 记录模板是否已归档到运维安全日志
- [ ] `make check-config` 启动校验：所有 ≥ 32 字节的 L4 密钥长度达标

### §6.6 扩展功能门禁（§5 相关）

- [ ] LLM 工具调用集新增成员：已 review 是否为只读 + 不可越权
- [ ] 埋点中间件字段变更：`user_id` 仍为 NULL + 无 body/header/PII
- [ ] OAuth 登录：state CSRF 校验 + 服务端换 token 双重保障未被绕过
- [ ] 默认管理员：critical=True + advisory lock 双保险仍生效，失败启动拒绝

---

> ↩ **返回后端架构总览**：[BackDoc-01-Arch.md](BackDoc-01-Arch.md) · **模块契约权威**：[BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md) · **前端侧安全**：[FrontDoc-02-Sec.md](../../../CS-Web-Frontend/tools/docs/FrontDoc-02-Sec.md)
