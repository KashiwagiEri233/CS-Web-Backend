# CS-Web-Backend

> 计算机社团官网后端 — FastAPI + PostgreSQL
>
> 由原 Next.js 全栈单体（CS-Web-Frontend）按模块分离而来：前端降级为「UI + BFF 薄转发」，
> 认证、数据、业务逻辑全部由本仓库接管。分离计划与 ADR 见根仓 [`CHANGELOG.md`](../CHANGELOG.md) 的「前后端分离迁移」一节。

## 技术栈

| 层 | 选型 |
|---|---|
| 框架 | FastAPI 0.139 + Starlette，async 全链路 |
| ORM / 迁移 | SQLAlchemy 2.0 async + Alembic（Schema 唯一来源） |
| 数据库 | PostgreSQL（asyncpg，专属库 `domefff`） |
| 认证 | JWT 双 Token（access 15min / refresh 7day，refresh 轮换 + 黑名单）、TOTP 2FA（RFC 6238 + HKDF/AES-256-GCM 加密）、GitHub OAuth、邮箱验证码 |
| 密码 | bcrypt（scrypt 登录懒升级兼容） |
| 工具链 | uv（`uv sync` 安装全部依赖） |

## 快速开始

```bash
# 1. 配置环境（先复制模板并改 SECRET_KEY / DATABASE_PASSWORD）
cp .env.development .env    # 开发；生产用 .env.example 模板

# 2. 安装依赖（Python 3.13+）
uv sync

# 3. 建库 + 迁移（开发环境启动时 DB_AUTO_MIGRATE=True 会自动 upgrade）
alembic upgrade head

# 4. 启动（--env 1 开发热重载 / --prod 生产 4 workers）
python run.py --env 1
# 或直接（uvicorn 默认 :8000；本地联调端口见仓库根 Makefile 的 BACKEND_PORT=9000）：
uvicorn app.main:app --reload
```

| --env | 配置文件 | 说明 |
|-------|---------|------|
| 1 | `.env.development` | 开发：DEBUG 日志 + 热重载 + 自动迁移 |
| 2 | `.env.test` | 测试：独立测试库 |
| 3 | `.env` | 生产：INFO + JSON 日志 + 多 worker |

启动后访问 `http://localhost:9000/docs`（Swagger）/ `/redoc` 查看全部 API。

**关键环境变量**（遗漏会启动失败或功能降级）：

- `SECRET_KEY`（≥32 字节）、`DATABASE_PASSWORD`、`ALLOWED_ORIGINS`（前端地址，如 `http://localhost:2333`）
- `TOTP_ENCRYPTION_KEY`（2FA 加密）、`COMMUNITY_IP_HASH_SECRET`（浏览去重 IP 哈希，≥16 字节必填）、`PASSWORD_RESET_DEFAULT`（默认重置密码）
- `BACKEND_URL` 是前端侧配置（BFF 指向本仓库，默认 `http://localhost:9000`）

## 模块清单

| 模块 | 能力 | 路由前缀 |
|---|---|---|
| 认证 / 用户 | 邮箱登录（防枚举）、注册验证码、TOTP 2FA、GitHub OAuth、JWT 刷新/登出、个人资料/头像、设备会话管理、公开主页 | `/api/v1/auth` `/users` |
| 公告 / 通知 | 公告公开列表 + 管理 CRUD、通知分页/已读/广播（like/reply/favorite/follow/mention 自动触发） | `/announcements` `/notifications` |
| 入社申请 | 游客+登录提交、管理员审批（→ 通知） | `/join` `/admin/join` |
| 管理员 | 用户管理（禁用/启封/重置密码，含 SELF/ROOT/LAST_ADMIN 保护）、角色/权限/操作审计、密码重置审批 | `/admin/*` |
| 活动 | CRUD + 筛选、报名（限额/去重）、签到核销、自动归档、批量/统计、设置 | `/events` |
| 社区 v2 | 统一内容（topic/post 一表）、评论/楼中楼、多态点赞收藏、浏览去重、@提及、审核（隐藏/恢复/置顶/加精/硬删）、关注流、举报处理、社区系列、草稿、上传、搜索（ILIKE 降级，GIN 优化见 Phase 6） | `/community/*` |
| 工具集 | 考试（组卷/自动判分/排名）、资源（提交/审核/上传）、任务（认领限额/审核 + 积分联动）、积分（流水/排行榜/7 级等级）、Auxilio 学习助手（薄弱标签→资源推荐）、组件注册表（item/variants/guide） | `/tools/*` `/admin/tools/*` |
| 系统 | 健康检查、异常日志、RBAC（角色-权限）、审计日志 | `/health` `/exceptions` `/admin/*` |

权限模型：`require_permission("resource", "action")` 细粒度控制，预置 root/admin/content_moderator/exam_admin/task_publisher 角色，权限名与前端权限 key 双向映射。

## 与前端的分工

```
浏览器 ──> Next.js (CS-Web-Frontend) ──proxy──> FastAPI (本仓库)
           · UI + 页面 + 客户端状态        · 全部业务 API（/api/v1）
           · BFF 薄转发（src/app/api/**）   · PostgreSQL + 迁移
           · JWT 存 HttpOnly Cookie        · JWT 签发/校验/轮换
```

- 前端 `backend-client.ts` 负责：Cookie 注入 Authorization、401 静默刷新重试、snake_case → camelCase 翻译
- 本地联调：前端 `BACKEND_URL=http://localhost:9000`，前端地址加入后端 `ALLOWED_ORIGINS`
- 生产 Cookie 用 `__Host-` 前缀（Secure + Path=/）

## 数据库与迁移

- 全环境仅用 Alembic（禁止 `create_all`），启动任务在 `DB_AUTO_MIGRATE=True` 时自动 `upgrade head`
- 迁移链：`d1e2f3a4b5c6`（业务基线 36 表）→ `f6a7b8c9d0e1`（refresh token 扩展）→ `h2i3j4k5l6m7`（roles 表扩展）→ `c8d9e0f1a2b3`（community v2 统一表，论坛+博客合并 + 关注/举报）
- 旧表（forum_* / blog_*）保留作数据迁移源，Phase 6 清理

## 测试与质量门

```bash
# 代码风格 / 类型
uv run flake8 app tests
uv run mypy app

# 单元测试（268 个，本机即可全跑）
uv run python -m pytest -q --no-cov -m "not integration and not queue_integration"

# PG 集成测试（需 Linux + PostgreSQL，验证流程见 tools/docs/BackDoc-Infra.md §六 迁移验证）
uv run python -m pytest tools/tests/features tools/tests/integration -v --no-cov
```

集成测试按 Phase 组织：`test_auth_phase1.py` / `test_phase2_modules.py` / `test_phase2_5_admin.py` /
`test_phase3_events.py` / `test_phase4_community.py`（v2）/ `test_phase5_tools.py`。

## 目录结构

```
app/
├── api/v1/            # 路由层（auth / users / admin_* / events / community / admin_community / tools / admin_tools / …）
├── core/              # 配置、JWT、异常体系、限流/缓存、事件总线、日志
├── middleware/        # CORS / 安全头 / 指标 / 限流 / RBAC 依赖
├── models/            # SQLAlchemy 2.0 模型（41+ 张表，含 community v2）
├── repositories/      # 数据访问层（只 flush，不 commit）
├── schemas/           # Pydantic v2 入参/出参
├── services/          # 业务逻辑（auth / community / events / exam / resource / task / points / …）
├── utils/             # 纯工具（掩码、图片校验…）
├── database.py        # 异步引擎 + get_db / get_session
└── main.py            # 应用入口（lifespan + 中间件）
alembic/               # 迁移（单一 head 链）
tools/tests/           # 单元测试 + integration/（PG 集成）
tools/docs/            # 验证指南（BackDoc-Infra.md §六 迁移验证）等
```

## 参考文档

| 文档 | 内容 |
|---|---|
| `tools/docs/BackDoc-Infra.md §六 迁移验证` | Linux/PG 环境验证指引（各 Phase 集成测试、2FA/密码兼容检查清单） |
| `CLAUDE.md` / `AGENTS.md` | 项目定位、扩展约定、Alembic 管理、不变量 |
| `tools/docs/BackDoc-Conv.md` | 编码规范与质量红线 |
