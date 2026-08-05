# 历史归档（Archive）（BackDoc-Archv）

> 更新人：3yearsZ
> 最后更新：2026-08-05（统一 BackDoc 命名）
> 注意：所有内容均为**已完成特性的历史演进痕迹**，**不作现行方案**。
> 当前能力请以 [BackDoc-Arch.md](BackDoc-Arch.md)、[BackDoc-Sec.md](BackDoc-Sec.md)、[BackDoc-Infra.md](BackDoc-Infra.md)、[BackDoc-Mods.md](BackDoc-Mods.md) 为准。
> 本文件合并了原 `docs/archive/` 目录下全部文档：
> 前后端分离迁移计划（`migration_plan.md`）与两个已完成特性的实现设计稿（`plans/`）。
> 所有内容均为**已完成特性的历史演进痕迹**，**不作现行方案**；当前能力请以根级文档
> `docs/BackDoc-Sec.md`、`docs/BackDoc-Infra.md`、`docs/BackDoc-Mods.md` 等为准。

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
  ├── middleware 链：CORS -> 异常 -> 安全头 -> 日志 -> 指标 -> 限流 -> 认证限流
  ├── api -> service -> repository -> model（单向分层）
  ├── RBAC：require_permission("res","act") + PermissionChecker 旁路
  └── 能力：JWT 双 token / 黑名单 / TOTP / OAuth / 限流 / 缓存 / arq 队列 / OTel / 健康检查
  ▼
PostgreSQL（domefff）← Alembic 管理全部 42+ 张表（含前端 36 张业务表）
Redis（可选增强）── 限流 / 缓存 / 2FA 防重放 / 跨实例黑名单
```

### 1.4 表清单映射（SQLite/Drizzle 36 张 -> SQLAlchemy 模型）

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
- `integer` 布尔 0/1 -> SQLAlchemy `Boolean`
- ISO 字符串日期 -> `DateTime(timezone=True)`（遵守 `../../CLAUDE.md` 双时区约定）
- partial unique index -> 迁移中手工 SQL
- JSON 列 -> `JSONB`

### 1.5 模块迁移路线图（6 个阶段）

> ℹ️ 变更记录/待办条目已迁移至根目录 `项目演变历史.md` / `项目待办事项.md`。

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

> ℹ️ 变更记录/待办条目已迁移至根目录 `项目演变历史.md` / `项目待办事项.md`。

### 1.8 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| JWT 切换导致全站登出 | P0 | Phase 1 先行独立验收；迁移窗口双登录态并存 |
| scrypt->bcrypt 迁移失败 | P0 | 懒升级 + 迁移脚本双保险 |
| FTS5->tsvector 搜索差异 | P1 | Phase 4 单独验收搜索排序/中文分词 |
| 双库写入期数据不一致 | P1 | 每模块完成才切流量；单写后端 |
| 契约漂移 | P1 | 契约比对脚本；错误码走 `ErrorCode` 注册表 |
| 上传/邮件能力缺失 | P1 | Phase 2 前补齐基础能力 |
| 单进程->多 worker 语义变化 | P1 | Redis 化，生产启用 `REQUIRE_REDIS_FOR_SECURITY` |

### 1.9 验收标准

> ℹ️ 变更记录/待办条目已迁移至根目录 `项目演变历史.md` / `项目待办事项.md`。

---

## 二、实现设计稿汇总（Plans）

> 两个设计稿均为**已完成特性**的规划文档，仅作演进痕迹保留。
> 现行实现细节见 `docs/BackDoc-Sec.md`（异常）、`docs/BackDoc-Infra.md`（日志）。

### 2.1 异常处理系统设计稿（fastapi-exception-handling-system）

> ℹ️ 变更记录/待办条目已迁移至根目录 `项目演变历史.md` / `项目待办事项.md`。

### 2.2 日志系统设计稿（fastapi-complete-logging-system）

> ℹ️ 变更记录/待办条目已迁移至根目录 `项目演变历史.md` / `项目待办事项.md`。
