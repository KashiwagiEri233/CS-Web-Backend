# MIGRATION_PLAN — FZTBU CS 前后端分离迁移计划

> 文档类型：planning + ADR 记录 | 受众：架构师 / 后端迁移实施者 / 前端 BFF 改造者
> 目标：将 CS-Web-Frontend（Next.js 全栈单体）中的全部后端功能（server 层 + API 路由 + 数据库访问）分离到本仓库（FastAPI WitchCat 脚手架），前端降级为纯 UI + BFF 薄转发。
> 最后更新：2026-08-01 | Stale 信号：模块迁移状态清单与实际代码不一致、表清单与 Alembic 迁移不符

---

## 一、背景与目标

### 1.1 现状

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

### 1.3 待决策清单（Open Questions，见 §8）

---

## 二、目标架构

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

---

## 三、表清单映射（SQLite/Drizzle 36 张 → SQLAlchemy 模型）

> 来源：前端 `src/shared/db/schema/*.ts`（Drizzle）+ `src/shared/db/migrations.ts`（password_history）+ `src/shared/db/schemas/*.ts`（SQLite DDL，含 FTS5）。
> 状态列：`已有` = 本仓库已存在；`新建` = 待迁移；`合并` = 与后端已有表合并或吸收。

| 模块 | 表 | 建议模型文件 `app/models/` | 状态 |
|---|---|---|---|
| 认证/用户 | users（含业务字段 display_name/bio/avatar/points/…） | `user.py` | **合并**：以现有 user.py 为基，补齐业务字段（见 §8 OQ-2） |
| | sessions | `user_session.py`（若保留会话记录能力）或废弃 | 待定（OQ-3） |
| | login_history | `login_history.py` | 新建 |
| | password_history | `password_history.py` | 新建 |
| | verification_codes | `verification_code.py` | 新建 |
| | password_reset_requests | `password_reset_request.py` | 新建 |
| 框架已有 | roles / permissions / user_roles / role_permissions | 已有 `role.py` `permission.py` | 已有 |
| | refresh_tokens | 已有 `refresh_token.py` | 已有 |
| | exception_logs | 已有 `exception_log.py` | 已有 |
| | audit_logs | 已有 `audit_log.py` | 已有（与前端 admin_actions 合并，见 OQ-1） |
| 系统 | settings | `setting.py` | 新建 |
| | component_registry_items / _variants / _guides | `component_registry.py` | 新建 |
| | resources | `resource.py` | 新建 |
| 入社 | join_applications | `join_application.py` | 新建 |
| 活动 | events / event_registrations / event_checkins / activity_participations | `event.py` | 新建 |
| 论坛 | forum_categories / forum_topics / forum_replies / forum_likes / forum_favorites / forum_topic_views / forum_mentions | `forum.py`（或按子域拆分） | 新建 |
| | forum_topics_fts（FTS5 虚拟表） | 不建 ORM；PG 用 GIN + tsvector 迁移 SQL | 新建（迁移内处理） |
| 博客 | blog_posts / blog_series / blog_likes | `blog.py` | 新建 |
| 通知 | notifications / announcements | `notification.py` `announcement.py` | 新建 |
| 考试 | exams / exam_questions / exam_question_options / exam_attempts | `exam.py` | 新建 |
| 任务/积分 | tasks / task_claims / points_transactions | `task.py` `points.py` | 新建 |

**迁移方式**：一次 Alembic baseline（`alembic revision --autogenerate`，把所有新模型一次性纳入首个大迁移 `add_cs_business_tables`），后续模块迭代增量迁移。禁止 `create_all`（见 AGENTS.md 铁律）。

**类型映射注意**（来自前端 Drizzle 双引擎经验）：
- `integer` 布尔 0/1 → SQLAlchemy `Boolean`
- ISO 字符串日期 → `DateTime(timezone=True)`（遵守 CLAUDE.md 双时区约定，出参继承 `TZModel`）
- partial unique index（root 唯一、登录/匿名浏览去重）→ 迁移中手工 SQL
- JSON 列（如 exam_questions 选项、component_registry variants）→ `JSONB`

---

## 四、模块迁移路线图（6 个阶段，每阶段可独立验收）

> 每阶段统一 SOP：
> 1. **契约**：从前端 `src/modules/<name>/types/index.ts` 提取 DTO → Pydantic v2 schema（入参校验 + `TZModel` 出参）
> 2. **数据**：模型 → `models/__init__.py` 登记 → Alembic 迁移
> 3. **实现**：`repositories/<x>_repo.py`（继承 `BaseRepository`）→ `services/<x>_service.py` → `api/v1/<x>.py` → 注册 `api/v1/__init__.py`
> 4. **横切**：错误码登记 `ErrorCode` 命名空间；配置项同步 `.env.example`
> 5. **测试**：`tests/` 镜像子包 + `docs/modules/<x>.md` 登记
> 6. **前端切换**：route handler 改薄转发 → 灰度 → 删 server 层代码
> 7. **验收**：本阶段 API 契约对比（字段/排序/分页/错误码）一致 + 前端 E2E 回归通过

### Phase 0 — 数据层与契约基线（✅ 数据层已完成 2026-08-01，DTO 骨架改由各阶段 SOP 内先行）
- ✅ 全量 36 表 SQLAlchemy 模型（`app/models/` 17 个文件，42 符号）+ 首个 Alembic 基线迁移
  `d1e2f3a4b5c6_add_cs_business_tables`（33 张新表 + users 扩展 8 业务字段；离线手写）
- ✅ 决策闭环：OQ-1 统一 audit_logs / OQ-2 扩展后端 users / Q-主键 全部 Integer（OQ-3/4 待 Phase 1）
- ⏳ **迁移验证**：本地无 PG，验证流程已写入 `docs/MIGRATION_VERIFICATION.md`，交由
  Linux/有 PG 环境执行（`alembic upgrade head` + `alembic check` 比对 + 约束冒烟 + 往返回滚）
- 📝 DTO 骨架：**不再预生成**——Pydantic schema 随各阶段「契约先行」SOP 逐模块产出（与
  服务实现同 PR，避免无主代码；OpenAPI 契约基线在 Phase 1 完成时生成首版）

### Phase 1 — 认证与用户（✅ 后端 + 前端 BFF 代码完成 2026-08-01；端到端联调待 Linux 环境）

- ✅ 邮箱登录（`/auth/login-email`，2FA 感知）+ 公开注册（验证码）+ 忘记密码申请流
- ✅ TOTP 2FA 全流程（setup/confirm/verify/disable/backup-codes；RFC 6238 + Node 交叉验证向量测试）
- ✅ GitHub OAuth（state 一次性 + 防接管语义）+ 邮件发送（smtplib，SMTP_HOST 空回退控制台）
- ✅ scrypt→bcrypt 懒升级（`app/core/password_compat.py`，含 Node 生成参考哈希测试）
- ✅ 2FA secret 同算法加密迁移（HKDF+AES-256-GCM，`app/core/totp_encryption.py`）
- ✅ profile CRUD + 预设/上传头像（魔数校验）+ 公开主页（论坛/考试统计）+ 改密（历史复用检测）
- ✅ 登录历史 + 设备列表/远程登出（refresh_tokens 增 ip_address/user_agent，迁移 `f6a7b8c9d0e1`）
- ✅ 新增表 two_factor_auth（Phase 0 迁移补齐）；密码重置审批（admin 路由 + 权限点 seed）
- ✅ 决策闭环：OQ-3 BFF HttpOnly Cookie / OQ-4 同算法迁移 / OQ-5 懒升级 / OQ-7 BFF 统一 401 刷新
- ✅ **前端 BFF 切换**（19 个路由薄转发）：`src/shared/backend-client.ts`（JWT cookie 托管 +
  401 静默刷新重试 + snake_case↔camelCase 翻译）+ `/api/auth/*` `/api/profile/*` `/api/sessions`
  `/api/avatars/*` 全部转换；新增 `tools/tests/backend-client.test.ts`（10 用例，mock fetch）；
  ts-check / eslint / vitest 通过（join.test.ts 23 个失败为本机既有问题，与本次改动无关）
- ⏳ 待验证（Linux/PG 环境）：
  1. `tests/integration/test_auth_phase1.py`（7 个流程，见 docs/MIGRATION_VERIFICATION.md §3b）
  2. 前后端联调：起后端（run.py）→ 起前端（BACKEND_URL 指向后端）→ 注册/登录/2FA/OAuth 全链路
  3. Phase 6 删除前端 `src/modules/auth/server`、`src/modules/user/server` 等 server 层（迁移收尾）

### Phase 2 — 基础小模块（✅ 后端完成 2026-08-01；前端 BFF 完成；admin roles/actions 翻译待子阶段）

- ✅ announcement：公开生效列表（角色定向）+ 管理员 CRUD/切换（`/announcements`，权限点 seed）
- ✅ notification：列表分页/未读数/已读/全部已读 + 管理员广播/群发记录聚合
- ✅ join：提交（游客/登录关联 userId）/我的申请 + 管理员审批（审计 + 站内通知）
- ✅ admin users：列表（搜索/角色/激活筛选）+ 详情/编辑/禁用/启用/默认密码重置/自定义重置/硬删除
  （保护规则全量移植：SELF_DISABLE/SELF_DELETE/ROOT_PROTECTED/FORBIDDEN/LAST_ADMIN/NO_CHANGE）
- ✅ 事件总线：`app/core/events.py`（进程内 async pub/sub，fire-and-forget）+ 通知订阅者
  （user.registered → 欢迎通知；多实例广播迁移到 arq 待 ADR-014 评估）
- ✅ 角色 seed：content_moderator / exam_admin / task_publisher 预建（权限随对应模块迁移补充）
- ✅ 前端 BFF：`/api/announcements` `/api/notifications/*` `/api/join/*` `/api/admin/announcements`
  `/api/admin/notifications` `/api/admin/join` `/api/admin/users*` 全部转薄转发（16 个路由）
- ⏳ 待验证（Linux/PG）：`tests/integration/test_phase2_modules.py`（5 个流程：公告生命周期/
  通知广播/入社审批/管理员保护规则/注册欢迎事件）
- ⏳ 子阶段 2.5（admin 聚合翻译）：~~`/api/admin/roles*` `/api/admin/permissions` `/api/admin/actions`
  → 后端 rbac/audit 已有等价 API；需后端 roles 表扩展（display_name/is_system/sort_order 列 +
  迁移）后做 BFF 翻译，单独迭代~~ → ✅ 已完成 2026-08-01：
  - roles 表扩展 display_name/is_system/sort_order（迁移 `h2i3j4k5l6m7`），种子角色标记 is_system
  - 后端 `/admin/roles` CRUD + 权限全量替换（权限名自动创建）+ `/admin/permissions` 列表
  - 审计删除：`DELETE /audit/logs/{id}` + `DELETE /audit/logs?before=`（仅 root）
  - 前端 BFF：roles/roles[key]/roles[key]/permissions/permissions/actions/actions[id] 7 个路由
    （权限 key 双向映射 module.resource.action ↔ resource:action）
  - 集成测试 `tests/integration/test_phase2_5_admin.py`（Linux 跑）

### Phase 3 — 活动 events（✅ 后端 + 前端 BFF 完成 2026-08-01）

- ✅ 活动 CRUD：列表（status/search/tag 筛选 + 报名人数）、详情、创建（广播通知）、编辑、删除、批量状态更新
- ✅ 报名：限额校验（FULL 409）、重复报名 409、取消/重新报名、管理员代报名/改状态、报名统计
- ✅ 签到：批量生成签到码（幂等 skip）、现场核销（无效码/重复使用）、签到统计
- ✅ 自动归档：日期已过 → ended（date 自由格式归一化比较，前端 R17 修复语义对齐）
- ✅ 活动设置：settings 表（module=events）读写/重置，默认值对齐前端 DEFAULT_EVENT_SETTINGS
- ✅ 事件通知：event.created → 全站广播 / event.registered / event.cancelled → 站内通知（event_bus）
- ✅ 权限点：event:read/create/update/delete/batch_update/registration_manage/checkin_generate/checkin_verify/settings
- ✅ 前端 BFF：`/api/events*`（5）+ `/api/admin/events*`（10）共 15 个路由转薄转发（含事件翻译助手）
- ⏳ 待验证（Linux/PG）：`tests/integration/test_phase3_events.py`（5 个流程：CRUD+归档/报名流/签到流/批量+统计/设置）

### Phase 4 — 社区 community（✅ 后端 + 前端 BFF 完成 2026-08-01）

- ✅ 论坛：版块 CRUD（slug 唯一）、主题（列表筛选/详情含点赞收藏状态/创建/编辑/软删除 + 反范式计数）、
  回复（楼中楼/编辑/软删除）、点赞/收藏切换（like_count/favorite_count 反范式）、浏览去重
  （24h 窗口 + partial unique index + ON CONFLICT）、@提及（forum_mentions + 站内通知）
- ✅ 审核：隐藏/恢复/置顶/加精/硬删除（主题与回复）+ content_moderator 角色权限 seed
- ✅ 博客：文章 CRUD（slug 唯一/发布/归档/草稿）+ 点赞/浏览 + 系列 + Markdown TOC 提取
- ✅ 成员名录（tech_tags 筛选 + 脱敏）+ Feed 聚合（主题/文章/成员三源合并、标签/搜索/分页）+ 聚合标签
- ✅ 图片上传：论坛图 ≤5MB 魔数校验 + 静态服务（防路径遍历）
- ✅ **搜索降级**：FTS5 → 关键词 AND 语义 ILIKE（标题+内容）；GIN tsvector 全文索引列入 Phase 6 优化项
- ✅ 权限点：forum:read/update/delete/hide/restore/pin/feature/category_* + blog:update
- ✅ 前端 BFF：公开 23 个路由 + 管理 14 个路由（共 37 个）转薄转发（含 6 个翻译助手）
- ⏳ 待验证（Linux/PG）：`tests/integration/test_phase4_community.py`（5 个流程：版块+主题/回复+互动/审核/博客/成员+Feed）

### Phase 5 — 工具集 tools（17 文件）
- exam：CRUD / 组卷 / 答题自动判分（事务）/ 排名 / 我的成绩
- resource：分类 / 提交审核 / 上传
- task：发布 / 认领（UNIQUE(task_id, user_id)）/ 审核 / 积分联动
- component-registry：组件注册表 + variants + guides
- points：积分流水 + 排行榜；auxilio：学习助手规则引擎（薄弱标签 + 资源推荐，纯函数，易迁移）
- 前端 `/api/tools/*`、`/api/admin/tools/*` 切转发

### Phase 6 — 数据迁移与下线
- SQLite → PG 数据迁移脚本（按表导出、日期 ISO→timestamp、自增 ID 冲突处理）
- 全量契约比对 + 灰度切换（模块级）
- 删除前端 `src/modules/*/server`、`src/shared/db` 直连代码；保留 SQLite 仅为历史归档
- 更新前端 `Devdocs-migration-guide.md` / `Devdocs-pg-migration.md` 状态

---

## 五、横切面能力迁移清单（前端 → 后端对应物）

| 能力 | 前端现状（单进程假设） | 本仓库能力 | 动作 |
|---|---|---|---|
| 认证 | session cookie + scrypt | JWT 双 token + bcrypt + 黑名单 | 已就绪（Phase 1 适配） |
| RBAC | 6 角色 × 20+ 权限点（`shared/security/permissions.ts`） | RBAC 完整 CRUD + require_permission | 权限点种子数据对齐（roles/permissions 表） |
| 速率限制 | 内存 Map（登录 5/min、写操作 5-10/min） | 可降级 Redis/内存限流 | 按路由配置对齐阈值 |
| 事件总线 | 进程内 EventEmitter | arq 队列（可选）+ eager 兜底 | 事件定义移植 `event-types.ts` |
| 2FA 防重放 | 内存 consumed-jti Set | Redis SET + TTL | 已具备 Redis 能力 |
| 审计 | `admin_actions` 表手动埋点 | `audit_logs` + exception 落库 | 表合并决策 OQ-1 |
| 日志/链路 | pino + X-Request-Id | loguru + 请求日志 | 前端转发时透传 `X-Request-Id` |
| 上传/静态文件 | 磁盘直存（avatars/、forum-images/） | 无（需新增） | 新增 multipart 上传 + 魔数校验 + 静态托管（OQ-6） |
| 邮件 | nodemailer（SMTP） | 无（需新增） | 新增 aiosmtplib + arq 异步发送 |
| 健康检查 | `/api/health` | `/health` `/readyz` `/status` | 已就绪 |

---

## 六、前端 BFF 化改造要点

- `src/app/api/**/route.ts`：改为 `fetch(${BACKEND_URL}/api/v1/...)` 薄转发，透传 `Authorization` / `X-Request-Id` / Origin 校验逻辑保留在 BFF
- 新增环境变量 `BACKEND_URL`；`NEXT_PUBLIC_*` 中站内路径不变
- `src/server.ts` / `proxy.ts`：安全头、请求 ID 逻辑保留；转发层统一封装鉴权头注入
- 登录态：JWT 存储方案（OQ-3）确定后，在 BFF 统一注入，避免前端每处手写
- 前端测试：`tools/tests/*.test.ts` 中针对 server 层的单元测试随模块迁移同步改写为契约测试或删除；Playwright E2E 保留全量回归

## 七、工作量估算（粗）

| 项 | 前端侧 | 后端侧 |
|---|---|---|
| 迁移对象 | 66 server 文件、~140 路由 | 新增 ~10 模型文件、~15 schema、~12 repo、~15 service、~15 api 文件 |
| 测试 | 单元测试随迁/改写、E2E 回归 | 每模块镜像 pytest 子包 |
| 估算周期 | 每模块 1-2 周（含联调） | 全量约 10-14 周（单人） |

## 八、待决策清单（Open Questions）

| # | 问题 | 建议倾向 |
|---|---|---|
| OQ-1 | 审计表合并：前端 `admin_actions`（含 mask 脱敏字段）与后端 `audit_logs` 结构差异较大 | 以后端 `audit_logs` 为准并扩展脱敏字段；数据迁移时映射 |
| OQ-2 | users 表合并：后端 users（认证字段）与前端 users（业务字段 display_name/bio/avatar/points/tech_tags 等） | 扩展后端 users 表（单表），避免 profile 表分拆 |
| OQ-3 | 前端 JWT 存储：localStorage vs BFF httpOnly cookie 托管 | BFF 托管 httpOnly cookie 转发，保留 CSRF 防护（Origin 校验） |
| OQ-4 | TOTP secret 加密：前端 AES-256-GCM + HKDF 自实现，迁移后密钥体系 | 保留同算法解密→重加密，或用户重新绑定 2FA（迁移窗口强制重绑成本低） |
| OQ-5 | 密码哈希迁移：scrypt → bcrypt | 登录时懒升级（verify 通过后写 bcrypt），零停机 |
| OQ-6 | 上传文件存储：本地磁盘 / MinIO / S3 | 初期本地磁盘（复用 data/ 目录），预留对象存储抽象 |
| OQ-7 | refresh token 失效后前端登出策略（401 统一处理） | BFF 统一 401 拦截 + 静默刷新 |

## 九、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| JWT 切换导致全站登出/不可登录 | P0 | Phase 1 先行且独立验收；迁移窗口双登录态并存（OQ-3 的 BFF 托管方案下前端无感） |
| scrypt→bcrypt 迁移失败 | P0 | 懒升级 + 迁移脚本双保险；保留旧哈希读取路径直至无存量 |
| FTS5→tsvector 搜索行为差异 | P1 | Phase 4 单独验收搜索排序/中文分词（pg_trgm / zhparser 评估） |
| 双库写入期数据不一致 | P1 | 每模块完成才切流量；单写后端，前端直连代码即删 |
| 契约漂移（字段/错误码） | P1 | 契约比对脚本（前端 types ↔ Pydantic schema）；错误码走 `ErrorCode` 注册表 |
| 上传/邮件能力缺失阻塞迁移 | P1 | Phase 2 前补齐基础能力（§五） |
| 单进程 → 多 worker 语义变化（限流/防重放） | P1 | 后端已 Redis 化，生产启用 `REQUIRE_REDIS_FOR_SECURITY` |

## 十、验收标准（全部完成后）

- [ ] `/api/v1/**` 覆盖前端原 ~140 路由契约（OpenAPI 比对通过）
- [ ] 前端 `src/modules/*/server` 全部删除，`src/app/api/**` 全为薄转发
- [ ] SQLite 归档，生产仅 PG（Alembic 单一 head）
- [ ] 前端 E2E 全量回归 + 后端 pytest 全绿
- [ ] 本文档模块迁移状态清单、`docs/README.md` 索引、前端迁移指南同步更新
