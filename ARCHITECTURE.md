# ARCHITECTURE.md

本项目（企业级 FastAPI RBAC 权限管理脚手架）的系统设计与模块关系文档。
编码规范见 `CONVENTIONS.md`，扩展约定见 `AGENTS.md`，项目定位见 `CLAUDE.md`。

---

## 1. 系统定位

- **类型**：纯后端 REST API，无前端 / 模板 / 静态文件，所有接口返回 JSON。
- **核心能力**：RBAC 权限管理、JWT 认证、结构化异常处理、loguru 日志、可降级 Redis 限流 / 缓存、API 性能指标。
- **数据库**：PostgreSQL（asyncpg），专属库 `domefff`，禁止与其它项目共用一个库。
- **部署形态**：单进程开发 / 多 worker 生产（`python run.py --env 3 --prod`）。

---

## 2. 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI 0.110 |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| 迁移 | Alembic（仅生产） |
| 配置 | pydantic-settings v2 |
| 认证 | python-jose(JWT) + passlib |
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
│  在 models/__init__.py 汇总导出（create_all / alembic 依赖）│
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

```
BaseAppException（基类）
   └─ 各业务异常子类
        │
        ▼
setup_exception_handlers(app)   # 注册到 FastAPI，覆盖路由层异常
ExceptionHandlerMiddleware       # 最外层兜底，覆盖中间件层异常
exception_logging.py             # 异常落日志（写入 exception_log 表）
```

- 业务错误必须抛 `BaseAppException` 子类，由全局处理器统一映射状态码与响应体。
- 路由内禁止 `try/except` 吞业务异常再返回自定义格式。

### 4.3 认证与权限（`app/middleware/rbac.py` + `app/core/security.py`）

```
JWT 签发/校验  ──→  当前用户解析  ──→  权限校验依赖
  security.py          rbac.py            require_permission / require_role / require_superuser
```

- 鉴权用 **依赖注入**（`Depends(require_permission("res","act"))`），**禁止用装饰器**。
- `AUTH_ENABLED=False` 时全局放行为超级用户，仅本地开发；`DEBUG=False` 时置 False 会拒绝启动。
- Token 黑名单支持（`app/core/security_blacklist.py`），登出 / 改密后即时失效。

### 4.4 限流与缓存（`app/core/rate_limit/` + `app/core/cache/`）

```
                ┌── Redis 可用 ──→ Redis 后端
后端选择器 ──────┤
                └── Redis 未配置/故障 ──→ 内存后端（自动降级）
```

- Redis 是**增强项**，不是强依赖；未配置或故障自动降级到内存。
- 降级策略由 `RATE_LIMIT_FALLBACK` / `CACHE_FALLBACK` 控制。
- 启动时 `_initialize_redis` 仅探测连通性，**不阻断启动**。

### 4.5 日志（`app/core/loguru_logger.py`）

- 统一入口：`from app.core.loguru_logger import get_logger`。
- **禁止 `print`、禁止直接配置 loguru handler**。
- Profile：`LOG_PROFILE=dev`（DEBUG + 彩色控制台）/ `prod`（INFO + JSON + 文件轮转）。

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

| 使用场景 | API | 自动提交？ |
|---|---|---|
| 路由内（FastAPI 依赖） | `Depends(get_db)` | 否，需显式 `await db.commit()` |
| 路由外（worker/脚本/后台任务） | `async with get_session() as db:` | 否，需显式 commit；出异常自动回滚 |

- **统一不自动提交**：由调用方显式 commit，保证事务边界清晰。
- 引擎 `create_async_engine`，会话工厂 `AsyncSessionLocal(expire_on_commit=False)`。

---

## 7. 启动生命周期（`main.py` lifespan）

```
应用启动
  ├─ 检查 AUTH_ENABLED（关闭则告警）
  ├─ _initialize_database
  │    ├─ ensure_database_exists（DB_AUTO_CREATE_DATABASE=True 时）
  │    ├─ create_all（DB_AUTO_CREATE=True 时；开发/测试）
  │    └─ 连接检查
  ├─ _initialize_rbac（初始化权限/角色/管理员；失败不阻断启动）
  ├─ _initialize_redis（探测连通性；失败不阻断启动）
  └─ 日志输出启动状态
应用运行
应用关闭
  └─ close_redis_client
```

---

## 8. 模块依赖关系

```
main.py
  ├── app/api             （路由聚合）
  ├── app/middleware       （中间件注册）
  ├── app/core/exceptions  （异常处理器注册）
  ├── app/core/config      （settings）
  ├── app/core/loguru_logger
  ├── app/database         （engine、lifespan 用）
  └── app/models           （Base，create_all 用）

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

## 9. 目录与职责矩阵

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

## 10. 关键不变量（贯穿全项目，勿打破）

1. **分层单向**：api → service → repository → model；禁止反向 / 跨层。
2. **DB 会话**：路由 `Depends(get_db)`，路由外 `async with get_session()`；**都不自动提交**。
3. **时间列**：ORM 时间列一律 `timezone=True`。
4. **权限**：用依赖注入（`require_permission` 等），不用装饰器。
5. **业务异常**：抛 `BaseAppException` 子类，不在路由吞异常。
6. **中间件短路**：`return JSONResponse(...)`，不 `raise HTTPException`。
7. **日志**：`get_logger`，不 `print`、不直接配 handler。
8. **Redis 可降级**：限流/缓存把 Redis 当增强项，不是强依赖。
9. **配置单一来源**：`Settings` + `.env*`；新增字段同步 `.env.example`。
10. **迁移铁律**：`create_all` 与 `alembic` 不同库共存；开发 `create_all`，生产 `alembic upgrade head`。

---

## 11. 扩展指引（摘要）

新增一个 API 资源的完整配方见 `AGENTS.md`「加一个 API 资源」。要点：

1. `models/<x>.py` → 登记 `models/__init__.py`。
2. `schemas/<x>.py`（Pydantic v2）。
3. `repositories/<x>_repo.py`。
4. `services/<x>_service.py`。
5. `api/v1/<x>.py` → 注册到 `api/v1/__init__.py`。
6. 建表/迁移（按环境策略）。
7. `tests/` 镜像补测试。

**中心注册点**（必须登记，否则不生效）：ORM 模型、业务异常、中间件、配置项、API router、测试子包 `__init__.py`。

---

## 12. 参考文档

- `CLAUDE.md` — 项目定位、技术栈、硬性禁止项、启动/配置/测试速查。
- `AGENTS.md` — AI Agent 扩展约定、中心注册点、Alembic 迁移管理、不变量。
- `CONVENTIONS.md` — 编码规范、命名、质量红线、安全/错误处理约定。
- `tests/README.md` — 测试目录组织与运行方式。
- `docs/README.md` — 模块文档索引与「系统级/业务模块级」分类约定；详解见 `docs/system/`、`docs/modules/`。
