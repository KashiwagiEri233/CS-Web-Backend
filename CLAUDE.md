# CLAUDE.md

本项目是企业级 FastAPI RBAC 权限管理脚手架（纯后端）。本文件为 Claude Code 提供项目级指令，作用域内优先级高于通用工作流。

---

## 项目定位

- **纯后端 REST API 脚手架**，不包含任何前端/UI 逻辑（模板、静态文件、管理后台 Web 界面已移除）。
- 提供 RBAC 权限、JWT 认证、结构化异常处理、loguru 日志、限流、性能监控。
- 默认数据库为 PostgreSQL（asyncpg）。

## 技术栈

| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI 0.110 + Uvicorn |
| ORM | SQLAlchemy 2.0 (async) |
| 数据库驱动 | asyncpg（PostgreSQL） |
| 认证 | python-jose (JWT) + passlib (bcrypt) |
| 日志 | loguru |
| 迁移 | Alembic |
| 配置 | pydantic-settings + .env |
| 测试 | pytest + httpx + pytest-asyncio |

## 目录约定

```
app/
├── api/v1/          # 路由层（auth/users/rbac/exceptions/test_exceptions）
├── core/            # config / loguru_logger / security / validators / exceptions/
├── middleware/      # monitoring / rate_limit / rbac
├── models/          # ORM 模型
├── repositories/    # 数据访问层（每张表一个 repo）
├── schemas/         # Pydantic 入参/出参
├── services/        # 业务逻辑层
├── utils/           # db_initializer / status
├── database.py      # 异步引擎 + get_db
├── dependencies.py  # 认证依赖
└── main.py          # 应用入口
```

## 编码规范

### 分层与调用方向
- 严格分层：`api → service → repository → model`。
- 路由层不直接操作 ORM，必须通过 service → repository。
- 新业务模块按上述分层放置，禁止跨层调用。

### 命名
- 文件名、变量名用 snake_case。
- 类名用 PascalCase。
- 常量用 UPPER_SNAKE_CASE。

### 异步约定
- 数据库操作一律 async。
- 路由函数、service 方法使用 async def。
- 禁止在 async 路径中直接执行阻塞 IO。

### 日志
- 统一使用 `from app.core.loguru_logger import get_logger`。
- 日志配置由 `configure_logging` 在 `main.py` lifespan 中统一管理。
- 开发级（DEBUG=True）：DEBUG 级别 + 彩色控制台 + 完整回溯栈。
- 线上级（DEBUG=False）：INFO 级别 + JSON 序列化 + 文件轮转 + 独立 error 日志。
- 禁止直接 `print()` 调试输出。

### 异常处理
- 业务异常继承 `BaseAppException`（在 `app/core/exceptions/base_exceptions.py`）。
- 全局异常处理器通过 `setup_exception_handlers(app)` 注册。
- 错误响应统一走 `ErrorResponse` 模型。

### 配置
- 所有可配置项定义在 `app/core/config.py` 的 `Settings` 类。
- 从 `.env` 读取，`.env.example` 必须与 `Settings` 字段一一对应。
- `SECRET_KEY` 必须从环境变量设置，禁止使用默认值。

## 禁止事项

- 禁止引入前端模板引擎（Jinja2）、静态文件挂载、HTML 响应。
- 禁止引入 sqlite/aiosqlite 作为生产数据库（仅 PostgreSQL）。
- 禁止在 `LoguruAdapter.setLevel` 中调用 `loguru_logger.remove()`（会清掉全局 handler 配置）。
- 禁止提交 `*.db`、`logs/`、`.env` 到版本控制。

## 启动

```bash
python run.py              # 开发模式（热重载）
python run.py --prod       # 生产模式（多 worker）
```
