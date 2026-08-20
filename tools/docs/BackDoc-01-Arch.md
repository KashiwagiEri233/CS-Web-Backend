# 后端架构与业务模块（BackDoc-Arch）

> 更新人：3yearsZ
> 最后更新：2026-08-20（版本基线更新至 1.0.1；此前 v0.9.8：新增第 9 章「工作台与学习助手子系统」；业务模块契约全量并入本文 **Part B**）
> 关联：编码规范见 [BackDoc-03-Conv.md](BackDoc-03-Conv.md)；扩展约定与项目定位见 `../AGENTS.md`；安全与权限见 [BackDoc-02-Sec.md](BackDoc-02-Sec.md)；基础设施见 [BackDoc-Infra.md](BackDoc-Infra.md)；业务模块契约见本文 **Part B**；入职与工程约定见根级 `docs/Onboarding.md`（附录 B）

> **文档定位**：后端系统设计与模块关系权威文档（reference）。Source of truth：分层架构、横切关注点、请求生命周期、目录职责矩阵、关键不变量、扩展指引、**业务模块契约（Part B：认证 / 用户 / RBAC / 审计 / 工作台 / 学习助手 / API 统计中间件）**。前端 BFF 架构与 API 契约见 `CS-Web-Frontend/tools/docs/FrontDoc-01-Arch.md`。

本项目（企业级 FastAPI RBAC 权限管理脚手架）的系统设计与模块关系文档。
编码规范见 `BackDoc-03-Conv.md`，扩展约定与项目定位见 `../AGENTS.md`。

---




## 章节速查（导航）

- [1. 系统定位](#1-系统定位)
- [2. 技术栈](#2-技术栈)
- [3. 分层架构](#3-分层架构)
- [4. 横切关注点（Cross-cutting Concerns）](#4-横切关注点cross-cutting-concerns)
- [5. 请求生命周期（以鉴权接口为例）](#5-请求生命周期以鉴权接口为例)
- [6. 数据库会话管理（`app/database.py`）](#6-数据库会话管理appdatabasepy)
- [7. 启动生命周期（`main.py` lifespan + `app/core/lifecycle/`）](#7-启动生命周期mainpy-lifespan-appcorelifecycle)
- [8. 模块依赖关系](#8-模块依赖关系)
- [9. 工作台与学习助手子系统（架构视图，v0.9.8 已落地）](#9-工作台与学习助手子系统架构视图v098-已落地)
- [10. 目录与职责矩阵](#10-目录与职责矩阵)
- [11. 关键不变量（贯穿全项目，勿打破）](#11-关键不变量贯穿全项目勿打破)
- [12. 扩展指引（摘要）](#12-扩展指引摘要)
- [一、认证（Auth）](#一认证auth)
- [二、用户管理（Users）](#二用户管理users)
- [三、RBAC（角色 / 权限）](#三rbac角色-权限)
- [四、审计日志（Audit）](#四审计日志audit)
- [五、工作台（Workbench）](#五工作台workbench)
- [六、学习助手（Auxilio）](#六学习助手auxilio)
- [七、API 调用统计中间件（ApiUsageMiddleware）](#七api-调用统计中间件apiusagemiddleware)
- [信息缺口声明（Part B）](#信息缺口声明part-b)
- [13. 参考文档](#13-参考文档)

## 1. 系统定位

- **类型**：纯后端 REST API，无前端 / 模板 / 静态文件，所有接口返回 JSON。
- **核心能力**：RBAC 权限管理、JWT 认证、结构化异常处理、loguru 日志、可降级 Redis 限流 / 缓存、API 性能指标；以及 v0.9.8 落地的**工作台**（GitHub 贡献热力图 / API 调用统计 / 番茄钟专注记录）与**学习助手 Auxilio**（rule-based + LLM 可选，SSE 流式对话）。
- **数据库**：PostgreSQL（asyncpg），专属库 `domefff`，禁止与其它项目共用一个库。
- **部署形态**：单进程开发 / 多 worker 生产（`python run.py --env 3 --prod`）。

---

## 2. 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI 0.139 |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| 迁移 | Alembic（开发、测试、生产的 schema 唯一来源） |
| 配置 | pydantic-settings v2 |
| 认证 | PyJWT + bcrypt |
| 日志 | loguru（经 `get_logger` 封装） |
| 缓存/限流 | redis（可选，可降级到内存） |
| 测试 | pytest + httpx，`asyncio_mode=auto` |

---

## 3. 分层架构

```
┌──────────────────────────────────────────────────────────┐
│  HTTP 请求                                                │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│  Middleware 层（main.py 注册，外 → 内执行）                │
│  CORS → ExceptionHandler → SecurityHeaders →              │
│  Logging → Metrics → RateLimit → AuthRateLimit            │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│  API 层  app/api/v1/                                      │
│  路由定义、参数校验、鉴权依赖注入                          │
│  使用 Depends(get_db)、Depends(require_permission(...))    │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│  Service 层  app/services/                                │
│  业务逻辑编排，组合多个 repo，实现业务规则                 │
│  构造函数注入 db；不依赖 Request（worker/脚本可复用）      │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│  Repository 层  app/repositories/                         │
│  纯数据访问，只做 CRUD，不含业务规则                       │
│  构造函数注入 db: AsyncSession                             │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│  Model 层  app/models/                                    │
│  SQLAlchemy 2.0 ORM，时间列一律 timezone=True              │
│  在 models/__init__.py 汇总导出（alembic autogenerate 依赖）│
└──────────────────────────────────────────────────────────┘
```

**调用规则**：
- 单向自上而下；禁止反向依赖（model/repo 不能 import service/api）。
- service 之间允许调用，但**只能通过构造函数注入**，禁止方法内部 import 另一个 service。

---

## 4. 横切关注点（Cross-cutting Concerns）

### 4.1 中间件链（`main.py`）

执行顺序（外 → 内）：

```
CORS → ExceptionHandler → SecurityHeaders → Logging → Metrics → RateLimit → AuthRateLimit → 路由
```

注册顺序自内向外（Starlette 中后 `add_middleware` 的在外层）。

**关键不变量**：
- 中间件短路用 `return JSONResponse(...)`，**禁止 `raise HTTPException`**（异常处理器只覆盖路由层）。
- 异常处理中间件包裹所有功能中间件，保证功能中间件抛错也能被映射为正确状态码。
- CORS 在最外层，保证错误响应也带 CORS 头。

### 4.2 异常处理（`app/core/exceptions/`）

用 `BaseAppException` 子类表达业务失败，由全局处理器统一映射状态码与响应体；未处理异常由最外层 `ExceptionHandlerMiddleware` 兜底。错误码集中在 `ErrorCode` 注册表。详见 **`BackDoc-02-Sec.md`**「异常处理」节。

### 4.3 认证与权限（`app/middleware/rbac.py` + `app/core/security.py`）

鉴权用**依赖注入**（`Depends(require_permission("res","act"))`），**禁止用装饰器**；`AUTH_ENABLED=False` 时全局放行为超级用户（仅本地）。管理端路由统一挂 `Depends(require_admin_2fa())` 强制管理员 2FA（未启用 TOTP → `TWO_FACTOR_NOT_SETUP`）；开发环境可用 `ADMIN_2FA_REQUIRED=False` 豁免（仅 `APP_ENV=development` 允许，生产置 False 拒绝启动）。详见 **`BackDoc-02-Sec.md`**「鉴权与安全基础设施」节。

### 4.4 限流与缓存

Redis 是**增强项**，未配置/故障时自动降级内存；降级策略由 `RATE_LIMIT_FALLBACK` / `CACHE_FALLBACK` 控制。限流详见 **`BackDoc-02-Sec.md`**「请求限流」节，缓存详见 **`BackDoc-Infra.md`**「缓存」节。

### 4.5 日志

统一入口 `from app.core.loguru_logger import get_logger`；**禁止 `print`、禁止直接配置 loguru handler**。详见 **`BackDoc-Infra.md`**「可观测性」节。

---

## 5. 请求生命周期（以鉴权接口为例）

```
1. HTTP 请求到达
2. CORS → 异常处理 → 安全头 → 日志 → 指标 → 限流 → 认证限流
3. 路由层 app/api/v1/users.py
   - Depends(get_db) 注入会话
   - Depends(require_permission("user","read")) 校验权限
4. Service 层 app/services/user_service.py
   - 业务校验、组合多个 repo
5. Repository 层 app/repositories/user_repo.py
   - SQLAlchemy 查询，返回 ORM 对象
6. Service 组装结果 → Pydantic schema 序列化
7. 显式 await db.commit()（如有写操作）
8. 返回 JSON 响应
9. 中间件链反向执行（指标采集、日志记录）
```

---

## 6. 数据库会话管理（`app/database.py`）

路由内用 `Depends(get_db)`，路由外用 `async with get_session()`；**统一不自动提交**，由调用方显式 `await db.commit()`，保证事务边界清晰（repo 只 flush，service commit）。详见 **`BackDoc-Infra.md`**「数据库与事务」节。

---

## 7. 启动生命周期（`main.py` lifespan + `app/core/lifecycle/`）

启动 / 关闭的初始化逻辑走**任务注册表**：各能力模块用 `@register_startup` /
`@register_shutdown` 自注册，`lifespan` 只调 `run_startup()` / `run_shutdown()` 遍历执行。
新增启动任务无需回 `main.py`（与「中心注册点」哲学一致）。

**失败语义**：`critical=True` 任务失败 → raise 中止启动（DB、RBAC seed）；`critical=False` 失败 →
仅告警继续（Redis/OTel）。关闭阶段任何异常都吞掉只记日志，绝不向外抛。

**完整任务清单、priority 段约定与新增任务配方见 `tools/docs/BackDoc-Infra.md`**「启动/关闭任务注册表」节（唯一权威，不在此重复）。

---

## 8. 模块依赖关系

```
main.py
  ├── app/api             （路由聚合）
  ├── app/middleware       （中间件注册）
  ├── app/core/exceptions  （异常处理器注册）
  ├── app/core/config      （settings）
  ├── app/core/lifecycle   （run_startup / run_shutdown 驱动启动/关闭任务）
  ├── app/core/loguru_logger
  ├── app/database         （engine、lifespan 用）
  └── app/models           （Base / ORM，供 Alembic 与查询使用）

api/v1/*
  ├── Depends(get_db)
  ├── Depends(require_permission/role/superuser)
  └── 调用 services/*

services/*
  ├── 构造函数注入 db: AsyncSession
  ├── 调用 repositories/*
  └── 可注入并调用其他 service

repositories/*
  ├── 构造函数注入 db
  └── 操作 models/*

core/cache, core/rate_limit
  └── 依赖 core/redis_client（可降级）

core/security, middleware/rbac
  └── 依赖 models（User/Permission/Role）+ core/config
```

---

## 9. 工作台与学习助手子系统（架构视图，v0.9.8 已落地）

> 本节只保留子系统**架构视图**与跨模块事实（分层 / 请求路径 / 数据模型 / LLM 配置）。
> 模块级契约（接口路由 / 服务职责 / 降级与不变量 / 测试）见 **Part B**「五、工作台」「六、学习助手」「七、API 调用统计中间件」——不在此重复，避免漂移。

### 9.1 分层与请求路径

```
前端 src/modules/workbench（widgets：greeting-bar / today-tasks / pomodoro-player /
  exam-countdown / quick-notes / github-heatmap / api-usage-stats / assistant-chat）
        │  注册表配置驱动；含「工作台 / 学习助手」视图切换 Tab；
        │  数据备份（导出 / 导入 / 清空）在前端本地完成（无独立后端端点）
        ▼
前端 BFF（proxyBackend 薄转发，仅透传，不含业务规则）
        ▼
后端 API 层
   app/api/v1/workbench.py  → 前缀 /api/v1/workbench   （api/v1/__init__.py 注册 tags=["工作台"]）
   app/api/v1/auxilio.py    → 前缀 /api/v1/auxilio     （api/v1/__init__.py 注册 tags=["学习助手"]）
        ▼
Service 层
   ContributionService（contribution_service.py）    GitHub 贡献数据抓取 + 缓存
   AuxilioService（auxilio_service.py）              学习画像分析（薄弱点 + 资源推荐）
   auxilio_agent.py（run_chat / execute_tool）       学习助手编排 + Skills 工具调用
   llm_client.py（stream_chat / check_enabled）      OpenAI 兼容 + Anthropic 双协议流式
        ▼
Model 层  contribution_cache / api_call_logs / conversations / chat_messages /
           focus_sessions / llm_usage_logs / llm_configs
```

调用规则与全项目一致：路由 → service → model 单向；`api_usage` 统计中间件在 `main.py` 注册（见 Part B §七）。

### 9.2 数据模型（跨模块）

| 表 | 模型 | 关键字段 | 写入方 |
|---|---|---|---|
| `contribution_cache` | `ContributionCache` | user_id, platform, username, year, data(JSONB), total, streak, fetched_at | ContributionService |
| `api_call_logs` | `ApiCallLog` | user_id(NULL), endpoint, method, status, latency_ms, created_at | ApiUsageMiddleware |
| `conversations` | `Conversation` | user_id, title, created_at, updated_at | auxilio API |
| `chat_messages` | `ChatMessage` | conversation_id, role, content, tool_calls(JSONB), created_at | auxilio API |
| `chat_events` | `ChatEvent` | conversation_id, user_id, seq, event_type, payload(JSONB), created_at | auxilio API（Trajectory 事件流，append-only） |
| `focus_sessions` | `FocusSession` | user_id, duration_seconds, phase, sound_source, started_at | workbench POST /focus-sessions |
| `llm_usage_logs` | `LlmUsageLog` | user_id, provider, model, prompt/completion/total_tokens, latency_ms, status | auxilio API（流式结束后） |
| `llm_configs` | `LlmConfig` | user_id(PK), provider, api_key_encrypted, base_url, model, web_search_enabled, trajectory_enabled, updated_at | workbench PUT /llm-config |

迁移链（Alembic，当前 head = `e5f6a7b8c9d0`）：

```
a3b4c5d6e7f8 (chinese_fts_zhparser)
   └─ b0b1c2d3e4f5  contribution_cache + api_call_logs + conversations + chat_messages
        └─ c2d3e4f5a6b7  focus_sessions
             └─ d3e4f5a6b7c8  llm_usage_logs + llm_configs
```

### 9.3 LLM 可选配置与降级（跨模块，工作台 / 学习助手共用）

- 全局配置（`app/core/config.py`）：`LLM_PROVIDER`（默认 `none`）、`LLM_API_KEY`（默认 `None`）、`LLM_BASE_URL`（默认 `None`，OpenAI 兼容自定义网关）、`LLM_MODEL`（默认 `gpt-4o-mini`）、`LLM_TIMEOUT`（默认 `60`）、`LLM_MAX_TOKENS`（默认 `1024`）、`LLM_DAILY_BUDGET`（默认 `200`，**已在 `auxilio_agent.run_chat` 落地每日每用户 token 预算拦截**：单位千 tokens/日，默认 200 = 20 万 tokens，0 = 不限制）。
- **默认即规则模式**：`LLM_PROVIDER=none` 时 `check_enabled()` 抛 `LLMConfigError`，`auxilio_agent.run_chat()` 捕获后直接返回「学习画像 + 资源推荐」摘要，不调用任何模型。
- **启用方式（二选一，用户级优先）**：① 全局 `.env` 配 `LLM_PROVIDER` + `LLM_API_KEY`（可选 `LLM_BASE_URL`）；② 用户在前端「API 调用统计 → LLM 设置」自行接入 API Key，写入 `llm_configs`（`api_key` AES-256-GCM 加密，绝不回显明文）。用户级配置经 `_user_llm_overrides()` 读取，**优先级高于全局 `.env`**。
- **双协议**：`provider=anthropic` 走 Anthropic Messages API，否则走 OpenAI 兼容协议。`stream_options.include_usage=true` 在流尾回传 token 计量，落 `llm_usage_logs`。
- **7 个 Skills** 明细（含各工具说明）见 Part B §六「Skills」表。

---

## 10. 目录与职责矩阵

| 目录 | 职责 | 不允许做的事 |
|---|---|---|
| `app/api/v1/` | 路由、参数校验、鉴权注入 | 直接发 SQL、写业务规则 |
| `app/services/` | 业务规则、编排 repo | 直接 `Request` 依赖、发原始 SQL |
| `app/repositories/` | 数据访问、CRUD | 写业务规则、import service |
| `app/models/` | ORM 定义 | 写查询逻辑（那是 repo 的事） |
| `app/schemas/` | Pydantic 入/出参 | 包含业务逻辑 |
| `app/core/` | 基础设施（config/security/redis/cache/rate_limit/logger/exceptions） | 反向 import service/api |
| `app/middleware/` | HTTP 中间件（rbac/rate_limit/monitoring） | 用 `raise HTTPException` 短路 |
| `app/utils/` | 跨层纯工具函数 | 依赖 db、Request |

---

## 11. 关键不变量（贯穿全项目，勿打破）

1. **分层单向**：api → service → repository → model；禁止反向 / 跨层。
2. **DB 会话**：路由 `Depends(get_db)`，路由外 `async with get_session()`；**都不自动提交**。
3. **时间列**：ORM 时间列一律 `timezone=True`。
4. **权限**：用依赖注入（`require_permission` 等），不用装饰器。
5. **业务异常**：抛 `BaseAppException` 子类，不在路由吞异常。
6. **中间件短路**：`return JSONResponse(...)`，不 `raise HTTPException`。
7. **日志**：`get_logger`，不 `print`、不直接配 handler。
8. **Redis 可降级**：限流/缓存把 Redis 当增强项，不是强依赖。
9. **配置单一来源**：`Settings` + `.env*`；新增字段同步 `.env.example`。
10. **迁移铁律**：全环境仅 Alembic 管理 schema；禁止 `Base.metadata.create_all`。建库由 `DB_AUTO_CREATE_DATABASE` 控制。

---

## 12. 扩展指引（摘要）

新增一个 API 资源的完整配方见 `AGENTS.md`「加一个 API 资源」。要点：

1. `models/<x>.py` → 登记 `models/__init__.py`。
2. `schemas/<x>.py`（Pydantic v2）。
3. `repositories/<x>_repo.py`。
4. `services/<x>_service.py`。
5. `api/v1/<x>.py` → 注册到 `api/v1/__init__.py`。
6. 建表/迁移（按环境策略）。
7. `tests/` 镜像补测试。

**中心注册点**（必须登记，否则不生效）：ORM 模型、业务异常、中间件、配置项、API router、启动/关闭任务（`@register_startup`/`@register_shutdown`）、测试子包 `__init__.py`。

---

---

# Part B · 业务模块契约

> 本部分为业务模块契约（Part B）。
> 每个模块遵循统一模板：**概述 / 接口 / 配置 / 安全要点（或降级与不变量）/ 测试**。
> 路由表为**摘要**，完整契约（method / path / requestBody / responses / schemas）以根仓 `openapi.baseline.json` 为准，字段约束以代码 `app/schemas/` 为准（不重抄字段，避免漂移）。

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

`tools/tests/api/v1/test_auth.py`、`tools/tests/services/test_auth_service.py`、`tools/tests/features/auth/test_auth_token_lifecycle.py`、
`test_auth_phase1.py`（需 PG）、`tools/tests/core/test_totp.py`、`test_totp_encryption.py`、`test_password_compat.py`、`test_token_blacklist.py`。

### 前后端联动
- 前端模块：认证（`FrontDoc-01-Arch.md` Part B §2.2）；页面 `/login` `/register` `/profile`
- BFF：`/api/auth/*`（含 2fa / oauth）→ 后端 `/api/v1/auth/*`

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
| GET | `/users/{user_id}` | 公开 | 用户公开主页 + 社区/考试统计 |

### 安全

- 改密：`password_changed_at` + 微秒 JWT `pwd_at`；同事务 `revoke_all_for_user`。
- 自助改密必须校验旧密码，防 access 泄露被接管；管理端重置不需要。
- 密码 ≤72 UTF-8 字节，避免 bcrypt 静默截断。
- 软删释放 username/email 唯一键（截断拼接后缀）。
- 头像四重校验（大小/MIME 白名单/扩展名白名单/文件头魔数）；文件名服务端生成。
- 公开主页仅返回已激活未软删用户。

### 测试

`tools/tests/api/v1/test_users.py`、`tools/tests/services/test_user_service.py`、`tools/tests/features/auth/test_auth_phase1.py`。

### 前后端联动
- 前端模块：个人资料（`FrontDoc-01-Arch.md` Part B §2.3）；页面 `/profile` `/users/[id]`
- BFF：`/api/profile/*`、`/api/avatars/*` → 后端 `/api/v1/profile/*`、`/api/v1/avatars/*`

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

### 前后端联动
- 前端模块：管理后台（`FrontDoc-01-Arch.md` Part B §2.7）；页面 `/admin/**`
- BFF：`/api/admin/*` → 后端 `/api/v1/admin/*`（BFF `requireAdmin/requireRoot` 仅 UI 兜底，本模块为权威 enforce）

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

### 前后端联动
- 前端模块：管理后台审计区（`FrontDoc-01-Arch.md` Part B §2.7 7.6）；页面 `/admin`（审计）
- BFF：`/api/admin/actions` → 后端 `/api/v1/admin/*`（审计端点，`system:logs` / `root`）

---

## 五、工作台（Workbench）

### 概述

聚合个人效率与学习数据：GitHub 贡献热力图、API 调用统计、番茄钟专注记录、LLM 用量与用户级模型配置。前端以注册表驱动的 widget 组合呈现（含「工作台 / 学习助手」视图切换 Tab）；后端只提供薄 API 与数据服务，不含前端布局逻辑。数据备份（导出 / 导入 / 清空）在前端本地完成，**无独立后端端点**。

代码：`app/api/v1/workbench.py`、`app/services/contribution_service.py`、`app/models/contribution.py`、`app/models/focus.py`、`app/models/api_usage.py`、`app/models/llm_config.py`、`app/models/llm_usage.py`。挂载：`/api/v1/workbench`。

### 接口

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/workbench/contributions/github` | 当前活跃用户 | GitHub 贡献热力图（近一年，6h 缓存，stale 降级），`username` / `year` / `refresh` 可选 |
| GET | `/workbench/stats/api-usage` | 当前活跃用户 | API 调用统计：今日计数 + 近 N 天趋势 + endpoint 分布（Top10） |
| POST | `/workbench/focus-sessions` | 当前活跃用户 | 番茄钟完成一轮专注后上报（`duration_seconds` / `phase` / `sound_source`） |
| GET | `/workbench/stats/pomodoro` | 当前活跃用户 | 番茄钟专注统计：总轮数 / 总时长 / 今日 / 近 N 天分布 |
| GET | `/workbench/stats/llm-usage` | 当前活跃用户 | 学习助手 LLM 用量：调用次数 / token 消耗 / 趋势 / 模型分布 |
| GET | `/workbench/llm-config` | 当前活跃用户 | 读取用户级 LLM 配置（apiKey 仅回显掩码） |
| PUT | `/workbench/llm-config` | 当前活跃用户 | 保存用户级 LLM 配置（API Key AES-256-GCM 加密存储） |

> schema 详见 `app/schemas/workbench.py`（如有）/ 对应 `app/models/*`；不在本文重抄字段。路由表为摘要，完整契约（method / path / requestBody / responses）以根仓 `openapi.baseline.json` 为准。

### contribution_service（GitHub 贡献热力图）

`app/services/contribution_service.py` 的 `ContributionService`：抓取 GitHub 公开贡献页（`https://github.com/users/{username}/contributions`，**未走 OAuth**，解析 `data-count` 旧版 `rect` 或新版 `td + tooltip`），按 `user_id + platform + year` 缓存于 `contribution_cache`。缓存 6h（`CACHE_TTL_SECONDS = 6*3600`），过期或 `refresh=true` 才重抓；抓取失败回退旧缓存并置 `stale=true`，无旧缓存则上抛。

### 配置

无专属配置项（GitHub 抓取不需要 token；全局 `SITE_URL` 仅用于 OAuth 回调，与此无关）。LLM 相关配置见 Part A §9.3 与「六、学习助手」配置节。

### 降级与不变量

- 抓取失败 → 回退旧缓存 + `stale=true`；无旧缓存 → 上抛 5xx，由全局异常处理器映射。
- `POST /focus-sessions` 幂等不校验重复（前端只报完成轮）。
- `llm-config`：API Key 加密存储，读取仅回显掩码（前 4 后 4），绝不回传明文 / 日志。

### 测试

[待填写]（未检索到 workbench 路由 / contribution_service / focus-sessions 的专属测试文件）

### 前后端联动
- 前端模块：工作台（`FrontDoc-01-Arch.md` Part B §2.18）；页面 `/tools`（工作台视图）
- BFF：`/api/workbench/*` → 后端 `/api/v1/workbench/*`（widget：github-heatmap / llm-usage-stats / pomodoro / api-usage-stats 等）

---

## 六、学习助手（Auxilio）

### 概述

rule-based + LLM 可选的学习助手。SSE 流式对话，支持 OpenAI / Anthropic 双协议与 Skills 工具调用；无 LLM 配置时降级为「学习画像 + 资源推荐」规则摘要。会话与消息落库（`conversations` / `chat_messages`）。

代码：`app/api/v1/auxilio.py`、`app/services/auxilio_agent.py`、`app/services/auxilio_service.py`、`app/services/llm_client.py`、`app/models/conversation.py`、`app/models/llm_usage.py`。挂载：`/api/v1/auxilio`。

### 接口

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/auxilio/chat` | 当前活跃用户 | SSE 流式对话（`text/event-stream`，双协议 + Skills；请求体可选 `preset_id` 指定 Agent 预设） |
| GET | `/auxilio/conversations` | 当前活跃用户 | 当前用户会话列表（按 `updated_at` 倒序，默认 20 条，最大 50） |
| GET | `/auxilio/conversations/{conversation_id}/messages` | 当前活跃用户 | 指定会话消息历史（含 `toolCalls`） |
| GET | `/auxilio/conversations/{conversation_id}/events` | 当前活跃用户 | Trajectory 事件回放（按 `seq` 升序返回 `chat_events` 全事件流，融合点 2 消费端） |

> 路由表为摘要，完整契约（method / path / requestBody / responses / SSE 事件形状）以根仓 `openapi.baseline.json` 为准。

### 服务职责

- **AuxilioService**（`app/services/auxilio_service.py`）：基于用户答题历史（`exam_attempts` + `exam.tech_tags`）计算各标签正确率，正确率 < 60%（`WEAKNESS_THRESHOLD`）标记为薄弱点，并按薄弱标签推荐已审核资源（`resource`，最多 10 条）。
- **auxilio_agent**（`app/services/auxilio_agent.py`）：学习助手编排核心。`run_chat()` 产出统一事件流（`delta` / `tool_call` / `tool_result` / `usage` / `done` / `error`），最多 `MAX_TOOL_ROUNDS = 3` 轮工具循环；注入系统提示词（`build_system_prompt`）并以声明式注册表 `TOOL_REGISTRY`（`ToolSpec`）注册 7 个 Skills（`TOOL_SCHEMAS` 由注册表推导，见下）；数据访问收敛至 `app/repositories/auxilio_tool_repo.py`（`AuxilioToolRepository`，只读）。
- **Trajectory 事件日志（融合点 2）**：`/auxilio/chat` 路由在事件循环内将每个事件（`delta` / `tool_call` / `tool_result` / `done` / `error`）append-only 落 `chat_events`（conversation_id / user_id / seq 自增 / event_type / payload JSONB / created_at），best-effort 失败不影响对话；`chat_messages` 保留为对外快照，`chat_events` 用于回放与调试。
- **llm_client**（`app/services/llm_client.py`）：统一流式入口 `stream_chat()`，按 `provider` 分流 OpenAI 兼容（`/chat/completions`）与 Anthropic（`/v1/messages`）双协议，产出统一事件 dict；`check_enabled()` 在未配置时抛 `LLMConfigError`（上层捕获后降级规则模式）。

### Skills（8 个，`auxilio_agent.TOOL_SCHEMAS`，由 `TOOL_REGISTRY` 推导）

| Skill | 说明 |
|---|---|
| `analyze_learning_profile` | 分析用户答题历史，返回薄弱知识点（正确率 < 60%）与推荐资源 |
| `get_exam_countdown` | 查询最近进行中考试及其截止倒计时 |
| `list_tasks` | 列出已发布协会任务（标题 / 分类 / 积分 / 状态），最多 10 条 |
| `list_my_claims` | 列出当前用户已认领的任务 |
| `search_resources` | 资源库按标题/描述模糊搜索已审核资源（统一实现：全站搜索与学习助手共用 `AuxilioToolRepository.search_resources`，波次 A1） |
| `get_llm_usage_stats` | 查询学习助手 LLM 调用统计（次数 / token 消耗） |
| `get_pomodoro_stats` | 查询用户番茄钟专注统计（总轮数 / 今日分钟） |
| `web_search` | 联网搜索外部资料（DuckDuckGo 免费接口，无需 key；`WEB_SEARCH_ENABLED` 可关；结果经 ER-19 包裹，不可信） |

### Agent 预设（融合点 3，`auxilio_agent.AGENT_PRESETS`）

预设 = 系统提示词模板 + 工具子集 + temperature，按场景组合（`AgentPreset` 声明式注册）：

| 预设 id | 名称 | 工具子集 | temperature |
|---|---|---|---|
| `general` | 通用答疑 | 全部 8 个暴露工具 | 默认 |
| `exam_sprint` | 考试冲刺 | analyze_learning_profile / get_exam_countdown / search_resources | 0.3 |
| `resource_finder` | 资源检索 | search_resources / analyze_learning_profile | 0.5 |
| `web_research` | 联网研究 | web_search / search_resources / analyze_learning_profile | 0.4 |

- `run_chat(preset_id=...)` 显式指定（`/auxilio/chat` 请求体 `preset_id`）；缺省按用户首条消息关键词启发式匹配（`match_preset`，考试类 → exam_sprint、资源类 → resource_finder，有序优先），无效 id 视同未指定。
- 工作台小组件为 lite 纯轻聊（不传 preset_id，走启发式）；全量页 `/tools/auxilio`（前端 `modules/auxilio/ui/agent-page.tsx`）提供预设切换。

### 配置

LLM 配置（全局 / 用户级）详见 Part A §9.3：`LLM_PROVIDER`（默认 `none`）、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`（默认 `gpt-4o-mini`）、`LLM_TIMEOUT`（默认 `60`）、`LLM_MAX_TOKENS`（默认 `1024`）、`LLM_DAILY_BUDGET`（默认 `200`，已在 `run_chat` 落地每日预算拦截）。用户级 `llm_configs` 优先级高于全局 `.env`。

### 降级与不变量

- LLM 未配置 → `check_enabled()` 抛 `LLMConfigError` → 规则模式摘要（不调用模型）。
- 流式中途异常 → 仍发出 `error` 事件，并 best-effort 持久化已完成内容。
- 会话归属校验：非本人会话返回 404（`_own_conversation`）。
- 工具执行异常 → 转为 result 文本回填，不中断对话循环。

### 测试

`tools/tests/features/tools/test_phase5_tools.py::test_auxilio`（覆盖 `AuxilioService.analyze_learning_profile` 学习画像分析）。

### 前后端联动
- 前端模块：学习助手（`FrontDoc-01-Arch.md` Part B §2.19）；页面 `/tools/auxilio`、工作台 assistant 视图
- BFF：`/api/tools/auxilio/*`（chat SSE / conversations）→ 后端 `/api/v1/auxilio/*`；画像 `/api/v1/tools/auxilio`
- LLM 配置经前端工作台「LLM 设置」→ `/api/workbench/llm-config`（见「五、工作台」）

---

## 七、API 调用统计中间件（ApiUsageMiddleware）

### 概述

`app/middleware/api_usage.py` 的 `ApiUsageMiddleware` 是**纯 ASGI 埋点中间件**，把每个请求写入 `api_call_logs`（fire-and-forget），供工作台 `GET /workbench/stats/api-usage` 消费。**无对外路由**。注册于 `main.py` 中 `LoggingMiddleware` 之外层、`SecurityHeadersMiddleware` 之内层。

### 写入与过滤

- 落库表：`api_call_logs`（`app/models/api_usage.py`）。
- 静默前缀（跳过自指噪声）：`/health`、`/readyz`、`/docs`、`/openapi.json`、`/workbench/stats/api-usage`。
- endpoint 归一化：`/api/v1/tools/exam/123` → `/api/v1/tools/exam/{id}`（数字段视为 id），避免统计键爆炸。
- `user_id` 当前恒为 `NULL`（原始 ASGI 层不解码 JWT，埋点按 endpoint 聚合，不绑定具体用户）。

### 配置 / 不变量

- 无专属配置项；写库失败静默（`create_task` + try/except），**绝不阻塞主流程**。
- 延迟取自响应 `http.response.start` 的 status 与请求进入时刻之差。

### 测试

[待填写]（未检索到 ApiUsageMiddleware 的专属测试文件）

### 前后端联动
- 无独立前端模块（埋点中间件，不暴露路由）；数据由前端工作台 `api-usage-stats` widget（`FrontDoc-01-Arch.md` Part B §2.18，部分就绪）经 `GET /api/workbench/stats/api-usage` 消费

---

## 信息缺口声明（Part B）

下列项未能从当前代码直接确认，已以 `[待填写]` 标记，需后续补实：

1. **工作台 / 贡献服务 / 番茄钟 / API 埋点 的专属测试文件**：在 `tools/tests/` 下未检索到对应测试（仅学习助手 `AuxilioService` 有 `test_phase5_tools.py::test_auxilio`）。
2. **数据备份（导出 / 导入 / 清空）后端端点**：当前 `workbench.py` 无对应路由，判定为前端本地实现；如确有后端接口需补充文档与路由表。
3. ~~**`LLM_DAILY_BUDGET` 强制逻辑**~~ → **已落实（2026-08-08）**：在 `auxilio_agent.run_chat` 调用模型前按用户累加当日 `llm_usage_logs.total_tokens`，达预算即停止并提示（详见 Part A §9.3）。

---

## 13. 参考文档

- `../AGENTS.md` — 项目定位、扩展约定、中心注册点、Alembic 迁移管理、不变量、硬性禁止项。
- `BackDoc-03-Conv.md` — 编码规范、命名、质量红线、安全/错误处理约定。
- `../tools/tests/README.md` — 测试目录组织与运行方式。
- `README.md` — 文档索引与分类约定；详解见 `BackDoc-02-Sec.md`、`BackDoc-Infra.md` 与本文 Part B。
