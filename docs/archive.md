# 历史归档（Archive）

> 本文件合并了原 `docs/archive/` 目录下全部文档：
> 前后端分离迁移计划（`migration_plan.md`）与两个已完成特性的实现设计稿（`plans/`）。
> 所有内容均为**已完成特性的历史演进痕迹**，**不作现行方案**；当前能力请以根级文档
> `docs/security.md`、`docs/infrastructure.md`、`docs/modules.md` 等为准。

---

## 一、前后端分离迁移计划（MIGRATION_PLAN）

> 文档类型：planning + ADR 记录 | 受众：架构师 / 后端迁移实施者 / 前端 BFF 改造者
> 目标：将 CS-Web-Frontend（Next.js 全栈单体）中的全部后端功能（server 层 + API 路由 + 数据库访问）分离到本仓库（FastAPI WitchCat 脚手架），前端降级为纯 UI + BFF 薄转发。
> 最后更新：2026-08-03（前端重建：适配上游 community v2 重构） | Stale 信号：模块迁移状态清单与实际代码不一致、表清单与 Alembic 迁移不符

---

### 1.1 背景与目标

| 项 | 前端 CS-Web-Frontend（现为全栈单体） | 后端 CS-Web-Backend（本仓库，脚手架） |
|---|---|---|
| 框架 | Next.js 16 App Router + React 19 | FastAPI 0.139 + SQLAlchemy 2.0 async |
| 数据库 | SQLite（better-sqlite3，生产在用）；Drizzle PG 双引擎 schema 已到 Phase 1 | PostgreSQL（asyncpg，专属库 `domefff`）+ Alembic |
| 认证 | session cookie + 自实现 scrypt/HKDF/AES-256-GCM + TOTP + GitHub OAuth | JWT 双 token（access 15min / refresh 7day）+ bcrypt + Token 黑名单 |
| 业务规模 | 9 模块、66 个 server 文件、~140 个 API 路由、36 张业务表 | 现有 auth / users / rbac / audit 4 个模块、6+ 张表 |
| 横切面 | 内存限流、进程内事件总线、pino 日志 | loguru、可降级 Redis 限流/缓存、arq 队列、OTel、健康检查 |

前端已具备与后端对齐的 PG schema 资产：`src/shared/db/schema/*.ts`（Drizzle，Phase 0+1 完成，36 表中 35 张已建模）。

### 1.2 已确认决策（ADR 摘要）

| # | 决策 | 说明 |
|---|---|---|
| D1 | 认证统一到后端 JWT | 采用脚手架原生 JWT 双 token；前端不再使用 session cookie；密码哈希由 scrypt 迁移到 bcrypt |
| D2 | 分阶段按模块交付 | 每模块独立验收（契约 + 数据 + API + 前端转发），禁止一次性全量搬迁 |
| D3 | 数据库：PG 唯一生产库 | Schema 唯一来源 = Alembic；SQLite 仅在迁移完成前作为前端开发 fallback |
| D4 | 前端降级为 BFF | `src/app/api/**/route.ts` 全部改为薄转发到本仓库；`src/modules/*/server` 迁移完成后删除 |

### 1.3 目标架构

```
浏览器
  │ HTTPS
  ▼
Next.js 16（UI 层）── 保留全部 page/SSR/RSC/组件；route handler 变薄转发
  │ REST/HTTP + Authorization: Bearer <JWT>（X-Request-Id 透传）
  ▼
本仓库 FastAPI /api/v1（统一前缀挂载）
  ├── middleware 链：CORS → 异常 → 安全头 → 日志 → 指标 → 限流 → 认证限流
  ├── api → service → repository → model（单向分层）
  ├── RBAC：require_permission("res","act") + PermissionChecker 旁路
  └── 能力：JWT 双 token / 黑名单 / TOTP / OAuth / 限流 / 缓存 / arq 队列 / OTel / 健康检查
  ▼
PostgreSQL（domefff）← Alembic 管理全部 42+ 张表（含前端 36 张业务表）
Redis（可选增强）── 限流 / 缓存 / 2FA 防重放 / 跨实例黑名单
```

### 1.4 表清单映射（SQLite/Drizzle 36 张 → SQLAlchemy 模型）

> 来源：前端 `src/shared/db/schema/*.ts`（Drizzle）+ `src/shared/db/migrations.ts` + `src/shared/db/schemas/*.ts`。
> 状态列：`已有` = 本仓库已存在；`新建` = 待迁移；`合并` = 与后端已有表合并或吸收。

| 模块 | 表 | 建议模型文件 `app/models/` | 状态 |
|---|---|---|---|
| 认证/用户 | users（含业务字段 display_name/bio/avatar/points/…） | `user.py` | **合并**：以现有 user.py 为基，补齐业务字段 |
| | sessions | `user_session.py`（若保留会话记录能力）或废弃 | 待定 |
| | login_history | `login_history.py` | 新建 |
| | password_history | `password_history.py` | 新建 |
| | verification_codes | `verification_code.py` | 新建 |
| | password_reset_requests | `password_reset_request.py` | 新建 |
| 框架已有 | roles / permissions / user_roles / role_permissions | 已有 `role.py` `permission.py` | 已有 |
| | refresh_tokens | 已有 `refresh_token.py` | 已有 |
| | exception_logs | 已有 `exception_log.py` | 已有 |
| | audit_logs | 已有 `audit_log.py` | 已有（与前端 admin_actions 合并） |
| 系统 | settings | `setting.py` | 新建 |
| | component_registry_items / _variants / _guides | `component_registry.py` | 新建 |
| | resources | `resource.py` | 新建 |
| 入社 | join_applications | `join_application.py` | 新建 |
| 活动 | events / event_registrations / event_checkins / activity_participations | `event.py` | 新建 |
| 论坛 | forum_categories / forum_topics / forum_replies / forum_likes / forum_favorites / forum_topic_views / forum_mentions | `forum.py` | 新建 |
| | forum_topics_fts（FTS5 虚拟表） | 不建 ORM；PG 用 GIN + tsvector 迁移 SQL | 新建 |
| 博客 | blog_posts / blog_series / blog_likes | `blog.py` | 新建 |
| 通知 | notifications / announcements | `notification.py` `announcement.py` | 新建 |
| 考试 | exams / exam_questions / exam_question_options / exam_attempts | `exam.py` | 新建 |
| 任务/积分 | tasks / task_claims / points_transactions | `task.py` `points.py` | 新建 |

**迁移方式**：一次 Alembic baseline，把所有新模型一次性纳入首个大迁移 `add_cs_business_tables`，后续模块迭代增量迁移。禁止 `create_all`（见 `../../AGENTS.md` 铁律）。

**类型映射注意**：
- `integer` 布尔 0/1 → SQLAlchemy `Boolean`
- ISO 字符串日期 → `DateTime(timezone=True)`（遵守 `../../CLAUDE.md` 双时区约定）
- partial unique index → 迁移中手工 SQL
- JSON 列 → `JSONB`

### 1.5 模块迁移路线图（6 个阶段）

> 每阶段统一 SOP：契约 → 数据 → 实现 → 横切 → 测试 → 前端切换 → 验收。

**Phase 0 — 数据层与契约基线**（✅ 数据层已完成 2026-08-01）
- ✅ 全量 36 表 SQLAlchemy 模型 + 首个 Alembic 基线迁移 `d1e2f3a4b5c6`（33 张新表 + users 扩展 8 业务字段）
- ✅ 决策闭环：OQ-1 统一 audit_logs / OQ-2 扩展后端 users / 主键全部 Integer
- ⏳ 迁移验证待 Linux/PG 环境（见 `docs/MIGRATION_VERIFICATION.md`）

**Phase 1 — 认证与用户**（✅ 后端 + 前端 BFF 代码完成 2026-08-01）
- ✅ 邮箱登录 + 公开注册（验证码）+ 忘记密码申请流
- ✅ TOTP 2FA 全流程（RFC 6238 + Node 交叉验证）+ GitHub OAuth + 邮件发送
- ✅ scrypt→bcrypt 懒升级 + 2FA secret 同算法加密迁移
- ✅ profile CRUD + 头像 + 公开主页 + 改密（历史复用检测）
- ✅ 登录历史 + 设备列表/远程登出 + 密码重置审批
- ✅ 前端 BFF 切换（19 个路由薄转发）

**Phase 2 — 基础小模块**（✅ 后端完成 2026-08-01；前端 BFF 完成）
- ✅ announcement / notification / join + admin users 管理（保护规则全量移植）
- ✅ 事件总线 `app/core/events.py` + 通知订阅者 + 角色 seed
- ✅ 前端 BFF 16 个路由薄转发
- ✅ 子阶段 2.5：roles 表扩展 + `/admin/roles` CRUD + 权限全量替换 + 审计删除

**Phase 3 — 活动 events**（✅ 后端 + 前端 BFF 完成 2026-08-01）
- ✅ 活动 CRUD + 报名（限额/去重）+ 签到核销 + 自动归档 + 批量/统计 + 设置
- ✅ 前端 BFF 15 个路由薄转发

**Phase 4 — 社区 community**（✅ 后端 + 前端 BFF 完成 2026-08-01）
- ✅ 论坛（版块/主题/回复/点赞收藏/浏览去重/@提及）+ 审核 + 博客 + 成员名录 + Feed 聚合
- ✅ 图片上传 + 搜索降级（FTS5 → ILIKE）
- ✅ 前端 BFF 37 个路由薄转发

**Phase 5 — 工具集 tools**（✅ 后端 + 前端 BFF 完成 2026-08-01）
- ✅ 考试（组卷/判分/排名）+ 资源（提交/审核）+ 任务（认领/审核→积分）+ 积分（流水/排行榜/等级）
- ✅ Auxilio 学习助手 + 组件注册表
- ✅ 前端 BFF 20 个路由薄转发

**Phase 6 — 数据迁移与下线**（⏳ 待 Linux/PG 环境执行）
- ⏳ 迁移脚本 `migrate-sqlite-to-pg.mjs`：按表导出 SQLite → PG，日期/ID/JSON 转换
- ⏳ 2FA 数据重加密 + scrypt 密码懒升级
- ⏳ 灰度切换 + 删除前端 server 层
- ⏳ 论坛搜索 GIN + tsvector 优化 + 事件总线跨实例（ADR-014）

### 1.6 横切面能力迁移清单

| 能力 | 前端现状 | 本仓库能力 | 动作 |
|---|---|---|---|
| 认证 | session cookie + scrypt | JWT 双 token + bcrypt + 黑名单 | 已就绪 |
| RBAC | 6 角色 × 20+ 权限点 | RBAC 完整 CRUD + require_permission | 权限点 seed 对齐 |
| 速率限制 | 内存 Map | 可降级 Redis/内存限流 | 阈值对齐 |
| 事件总线 | 进程内 EventEmitter | arq 队列（可选）+ eager 兜底 | 事件定义移植 |
| 2FA 防重放 | 内存 consumed-jti Set | Redis SET + TTL | 已具备 |
| 审计 | `admin_actions` 手动埋点 | `audit_logs` + exception 落库 | 表合并 |
| 日志/链路 | pino + X-Request-Id | loguru + 请求日志 | 透传 X-Request-Id |
| 上传/静态文件 | 磁盘直存 | multipart + 魔数校验 + 静态托管 | 已补齐 |
| 邮件 | nodemailer（SMTP） | aiosmtplib + arq 异步 | 已补齐 |
| 健康检查 | `/api/health` | `/health` `/readyz` `/status` | 已就绪 |

### 1.7 待决策清单（Open Questions）

| # | 问题 | 建议倾向 |
|---|---|---|
| OQ-1 | 审计表合并（`admin_actions` vs `audit_logs`） | 以后端 `audit_logs` 为准并扩展脱敏字段 |
| OQ-2 | users 表合并 | 扩展后端 users 表（单表） |
| OQ-3 | 前端 JWT 存储 | BFF 托管 httpOnly cookie 转发 |
| OQ-4 | TOTP secret 加密迁移 | 同算法解密→重加密，或强制重绑 |
| OQ-5 | 密码哈希迁移 scrypt→bcrypt | 登录时懒升级，零停机 |
| OQ-6 | 上传文件存储 | 初期本地磁盘，预留对象存储抽象 |
| OQ-7 | refresh 失效后登出策略 | BFF 统一 401 拦截 + 静默刷新 |

### 1.8 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| JWT 切换导致全站登出 | P0 | Phase 1 先行独立验收；迁移窗口双登录态并存 |
| scrypt→bcrypt 迁移失败 | P0 | 懒升级 + 迁移脚本双保险 |
| FTS5→tsvector 搜索差异 | P1 | Phase 4 单独验收搜索排序/中文分词 |
| 双库写入期数据不一致 | P1 | 每模块完成才切流量；单写后端 |
| 契约漂移 | P1 | 契约比对脚本；错误码走 `ErrorCode` 注册表 |
| 上传/邮件能力缺失 | P1 | Phase 2 前补齐基础能力 |
| 单进程→多 worker 语义变化 | P1 | Redis 化，生产启用 `REQUIRE_REDIS_FOR_SECURITY` |

### 1.9 验收标准

- [ ] `/api/v1/**` 覆盖前端原 ~140 路由契约（OpenAPI 比对通过）
- [ ] 前端 `src/modules/*/server` 全部删除，`src/app/api/**` 全为薄转发
- [ ] SQLite 归档，生产仅 PG（Alembic 单一 head）
- [ ] 前端 E2E 全量回归 + 后端 pytest 全绿

---

## 二、实现设计稿汇总（Plans）

> 两个设计稿均为**已完成特性**的规划文档，仅作演进痕迹保留。
> 现行实现细节见 `docs/security.md`（异常）、`docs/infrastructure.md`（日志）。

### 2.1 异常处理系统设计稿（fastapi-exception-handling-system）

- **最终实现**：`app/core/exceptions/` + `docs/security.md`「异常处理」节 —— ✅ 已完成，设计方向与实现一致。
- **定位**：为 FastAPI 建立完整异常处理系统，包括自定义异常类、全局异常处理器、异常日志记录和统一错误响应格式。
- **核心设计**：
  - 自定义异常类体系（业务/验证/权限异常）→ 最终 `BaseAppException` 子类体系
  - 全局异常处理器（统一捕获处理）→ 最终 `setup_exception_handlers` + `ExceptionHandlerMiddleware`
  - 异常日志记录（含请求上下文/堆栈）→ 最终异步落 `exception_log` 表
  - 统一错误响应格式（错误码/消息/详情）→ 最终 `ErrorCode` 注册表 + 统一响应模型
- **技术要点**：Python 继承 + Pydantic 验证；FastAPI `exception_handler` 装饰器；结构化日志；敏感信息过滤 + 请求 ID 追踪。
- **与实现的差异**：设计稿用独立的 `exceptions/handlers/logging/responses/middleware` 模块结构，最终实现收敛到 `app/core/exceptions/` 单包内，接口命名不同但职责一致。

### 2.2 日志系统设计稿（fastapi-complete-logging-system）

- **最终实现**：`app/core/loguru_logger/` + `docs/infrastructure.md`「可观测性」节 —— ✅ 已完成，但**技术选型不同**。
- **定位**：创建完整的日志系统层，提供结构化日志、多输出目标、日志级别控制、上下文追踪和性能监控。
- **核心设计**：
  - 兼容标准库 logging 的接口 → 最终 `LoguruAdapter`
  - 结构化日志（JSON）→ 最终 loguru JSON profile
  - 多输出目标（控制台/文件/数据库）→ 最终 console/file sink
  - 请求上下文追踪（correlation_id/user_id）→ 最终 `set_logging_context` / ContextVar
  - 日志轮转、异步写入、敏感信息脱敏 → 均已在 loguru 实现
- **⚠️ 重要差异**：原方案规划用 **structlog + orjson + PostgreSQL 落库**；最终落地采用 **loguru**（无 DB 落库）。因此设计稿中的 `logger_adapter/structured_logger/processors/handlers` 代码结构、`StructuredLoggerConfig`/`log_performance` 等接口与当前实现不一致，**仅作历史参考**。
