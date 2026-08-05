# 新手引导（Onboarding）（BackDoc-Onboard）

> 更新人：3yearsZ
> 最后更新：2026-08-05（统一 BackDoc 命名）
> 关联：架构见 [BackDoc-Arch.md](BackDoc-Arch.md)；编码规范见 [BackDoc-Conv.md](BackDoc-Conv.md)；业务模块见 [BackDoc-Mods.md](BackDoc-Mods.md)；扩展约定见 `../AGENTS.md`
> **文档类型**：tutorial + reference | **受众**：新加入的开发者 / 首次接触本仓库的贡献者
> **Source of truth**：本文件只做"入口引导"，具体细节一律指向各权威文档，不重复展开。
> **快速路径**：想加一个 API 资源 → 见「开发工作流」→ `AGENTS.md` 的「加一个 API 资源」配方。

---

## 1. 这是什么？

计算机社团官网的**纯后端服务**（FastAPI + PostgreSQL）。

- 前端 `CS-Web-Frontend` 为独立的「UI + BFF 薄转发」层；本仓库为**纯后端服务**，**所有认证、数据、业务逻辑都在本仓库**。
- 提供：JWT 认证（双 token）、RBAC 权限、TOTP 2FA、GitHub OAuth、可降级 Redis 限流/缓存、结构化日志（loguru）、可观测性（OTel）。
- 分层：`api → service → repository → model`，单向依赖。

> 定位与硬性禁止项见 `../CLAUDE.md`；扩展项目的结构约定见 `../AGENTS.md`。

---

## 2. 技术栈速览

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI 0.139（async 全链路） |
| ORM / 迁移 | SQLAlchemy 2.0 async + Alembic（schema **唯一来源**，禁止 `create_all`） |
| 数据库 | PostgreSQL（asyncpg），专属库 `domefff` |
| 认证 | JWT 双 token（access 15min / refresh 7day，refresh 轮换 + 黑名单）、TOTP 2FA、GitHub OAuth、邮箱验证码 |
| 密码 | bcrypt（scrypt 登录懒升级兼容） |
| 日志 | loguru（`get_logger` 统一入口，禁止 `print`） |
| 缓存/限流 | Redis（可选，故障自动降级内存） |
| 队列 | arq（**可选模块**，默认 eager 就地执行） |
| 工具链 | uv（`uv sync`）+ pytest / mypy / flake8 |

---

## 3. 快速开始

### 前置要求
- Python **3.13+**
- [uv](https://github.com/astral-sh/uv)（依赖管理）
- PostgreSQL 或 Docker（可选，本地单测默认用 SQLite/内存 mock）

### 一、配置环境

```bash
cp .env.development .env    # 开发模板；生产用 .env.example 模板
```

**必须修改的关键变量**（漏了会启动失败或功能降级）：

| 变量 | 说明 |
|---|---|
| `SECRET_KEY` | ≥32 字节随机串，JWT 签名 |
| `DATABASE_PASSWORD` | 数据库密码 |
| `ALLOWED_ORIGINS` | 前端地址（如 `http://localhost:2333`） |
| `TOTP_ENCRYPTION_KEY` | 2FA secret 加密 |
| `FORUM_IP_HASH_SECRET` | 浏览去重 IP 哈希 |
| `PASSWORD_RESET_DEFAULT` | 默认重置密码 |
| `ADMIN_PASSWORD` | 首次创建管理员 |

> 本地覆盖用**不跟踪**的 `.env.local` / `.env.*.local`。项目按约定跟踪 `.env`、`.env.development`、`.env.test`。

### 二、安装依赖

```bash
uv sync
```

### 三、建库 + 迁移

```bash
alembic upgrade head
# 开发环境 DB_AUTO_MIGRATE=True 时，启动会自动 upgrade，可跳过本步
```

### 四、启动

```bash
python run.py --env 1    # 开发：DEBUG + 热重载 + 自动迁移
# 或直接：
uvicorn app.main:app --reload --port 9000
```

访问 `http://localhost:9000/docs`（Swagger）查看全部 API。

| `--env` | 配置文件 | 说明 |
|---|---|---|
| 1 | `.env.development` | 开发：DEBUG + 热重载 + 自动迁移 |
| 2 | `.env.test` | 测试：独立测试库 |
| 3 | `.env` | 生产：INFO + JSON + 多 worker |

### 五、跑测试

```bash
# 单元测试（本机即可全跑）
uv run python -m pytest -q --no-cov -m "not integration and not queue_integration"

# PG 集成测试（需 Linux + PostgreSQL）
uv run python -m pytest tests/integration -v --no-cov

# 风格 / 类型
uv run flake8 app tests
uv run mypy app
```

---

## 4. 目录结构（一文看懂"东西放哪"）

```
app/
├── api/v1/            # 路由层：每个资源一个文件，在 v1/__init__.py 汇总注册
├── core/              # 基础设施：config / security / exceptions / cache / rate_limit / loguru_logger / lifecycle / events
├── middleware/        # HTTP 中间件：monitoring / rate_limit / rbac
├── models/            # SQLAlchemy ORM（models/__init__.py 汇总导出）
├── repositories/      # 数据访问：继承 BaseRepository，只 flush 不 commit
├── schemas/           # Pydantic 入/出参（带 datetime 的继承 TZModel）
├── services/          # 业务逻辑：组合 repo，显式 commit
├── utils/             # 跨层纯工具
├── database.py        # 引擎 + get_db（路由）/ get_session（路由外）
└── main.py            # 入口：中间件 + 异常处理器 + lifespan
alembic/               # 迁移（单一 head 链）
tests/                 # 镜像 app/ 结构 + integration/（PG 集成）
docs/                  # 本仓库文档（见下方索引）
```

---

## 5. 开发工作流：加一个 API 资源

完整配方在 `../AGENTS.md` 的「加一个 API 资源」。要点：

1. `models/<x>.py` → 登记到 `models/__init__.py`
2. `schemas/<x>.py`（Pydantic v2；带 datetime 的继承 `TZModel`）
3. `repositories/<x>_repo.py`（继承 `BaseRepository`）
4. `services/<x>_service.py`（组合 repo）
5. `api/v1/<x>.py` → 注册到 `api/v1/__init__.py`
6. 建表/迁移（Alembic）
7. `tests/` 镜像补测试
8. 业务模块**必须**在 `docs/BackDoc-Mods.md` 对应节登记（或新建 `docs/modules/<name>.md` 并登记到 `docs/README.md` 索引）

> **中心注册点**（必须登记，否则不生效）：ORM 模型、业务异常、中间件、配置项、API router、启动/关闭任务（`@register_startup`/`@register_shutdown`）、测试子包 `__init__.py`。

### 想改某个功能 → 看哪个文件？

| 想做什么 | 入口文件 |
|---|---|
| 加一个 HTTP 接口 | `app/api/v1/<模块>.py` |
| 改业务规则 / 校验 | `app/services/<模块>_service.py` |
| 改数据查询 | `app/repositories/<模块>_repo.py` |
| 改表结构 | `app/models/<x>.py` + Alembic 迁移 |
| 加配置项 | `app/core/config.py` + 同步 `.env.example` |
| 加错误码 | `app/core/exceptions/error_codes.py`（用 `ErrorCode.*`，禁裸字符串） |
| 加启动/关闭任务 | 在能力模块加 `@register_startup`/`@register_shutdown` + `lifecycle/__init__.py` 登记 import |
| 改认证 / 权限 | `app/core/security.py`、`app/middleware/rbac.py` |
| 改日志 | `app/core/loguru_logger/`（用 `get_logger`） |

---

## 6. 必须守住的约定（不变量速览）

> 完整版见 `docs/BackDoc-Arch.md` §10、`docs/BackDoc-Conv.md`。

1. **分层单向**：api → service → repository → model，禁止反向/跨层。
2. **DB 会话**：路由 `Depends(get_db)`，路由外 `async with get_session()`；**都不自动提交**——repo 只 flush，service 显式 commit。
3. **时间列**：ORM 一律 `DateTime(timezone=True)`；取当前时间用 `now_utc()`（`app/core/timezone.py`），**禁止** `datetime.now()`/`utcnow()`。
4. **出参时间**：带 datetime 的响应模型继承 `TZModel`（自动转本地时区）。
5. **权限**：用依赖注入 `Depends(require_permission("res","act"))`，**不用装饰器**。
6. **业务异常**：抛 `BaseAppException` 子类，不在路由吞异常。
7. **中间件短路**：`return JSONResponse(...)`，不 `raise HTTPException`。
8. **日志**：`get_logger`，不 `print`、不直接配 handler。
9. **Redis 可降级**：限流/缓存把 Redis 当增强项，不是强依赖。
10. **迁移铁律**：全环境仅 Alembic；禁止 `Base.metadata.create_all`。建库用 `DB_AUTO_CREATE_DATABASE`。
11. **时区**：核心存 UTC，展示走 `settings.TIMEZONE`；**必须装 `tzdata`**。
12. **新增 datetime 响应模型必须继承 `TZModel`**，不手写 per-field serializer。

---

## 7. 常见坑

| 坑 | 说明 |
|---|---|
| 任务/路由不生效 | 99% 是忘记在中心注册点登记（`models/__init__.py`、`v1/__init__.py`、`lifecycle/__init__.py`） |
| 启动失败"时区非法" | 缺 `tzdata`（尤其 Windows/alpine），展示层会误报；确保已装 |
| 时间多了/少了 8 小时 | 用了 naive `datetime`；统一走 `now_utc()` + `TZModel` |
| 测试连不上库 | `.env.test` 需 `DATABASE_URL` 指向**库名含 `test`** 的库（`tests/conftest.py` 校验） |
| 改了配置但无效 | 没同步 `.env.example`，或字段名与 `Settings` 不一致 |
| `alembic check` 报 drift | 别改历史迁移文件，新增增量迁移 |

---

## 8. 文档地图（本仓库 docs/）

| 文档 | 用途 |
|---|---|
| `README.md` | 文档索引 + 分类约定 + 模板（**从这里找其他文档**） |
| `BackDoc-Arch.md` | 系统架构总览（分层、中间件链、生命周期、不变量） |
| `BackDoc-Conv.md` | 编码规范、命名、质量红线 |
| `BackDoc-Onboard.md` | 本文件：新手引导 |
| `BackDoc-Sec.md` | 安全与防护（鉴权 / 异常 / 限流） |
| `BackDoc-Infra.md` | 运行基础设施（可观测性 / DB / 生命周期 / 队列 / 缓存） |
| `BackDoc-Mods.md` | 业务模块（认证 / 用户 / RBAC / 审计） |
| `BackDoc-MigV.md` | Linux/PG 环境迁移验证指南 |
| `BackDoc-Archv.md` | 历史归档（迁移计划 + 特性设计稿，不作现行方案） |
| `../CLAUDE.md` / `../AGENTS.md` | 项目定位 / 扩展约定（AI 协作也看这两个） |

---

## 9. 提交前检查清单

- [ ] 改了端点/签名/配置项 → 对应 `docs/BackDoc-Sec.md`/`BackDoc-Infra.md`/`BackDoc-Mods.md` 已更新
- [ ] 新增/改名公共函数或配置项 → 文档已同步
- [ ] 新建模块 → `docs/BackDoc-Mods.md` 登记或新建 `docs/modules/<name>.md` + 登记到 `docs/README.md` 索引
- [ ] `flake8` + `mypy` 通过
- [ ] 单元测试通过；改动涉及 DB 的补集成测试
