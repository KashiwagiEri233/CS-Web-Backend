# CLAUDE.md

企业级 FastAPI RBAC 权限管理脚手架（纯后端）。本文件优先级高于通用工作流。
**扩展项目的结构约定**（如何加模块、中心注册点、不变量）见 `AGENTS.md`。

## 项目定位
- 纯后端 REST API，无前端/模板/静态文件；所有接口返回 JSON。
- 提供 RBAC、JWT、结构化异常、loguru 日志、可降级 Redis 限流/缓存。
- 数据库 PostgreSQL（asyncpg）；**专属库 `domefff`，勿与其它项目共用一个库**。

## 技术栈
FastAPI 0.110 · SQLAlchemy 2.0 async + asyncpg · Alembic · pydantic-settings v2 · python-jose/passlib(JWT) · loguru · redis(可选) · pytest/httpx。

## 目录
```
app/
├── api/v1/        # 路由层（每个资源一个文件，在 v1/__init__.py 汇总注册）
├── core/          # config / loguru_logger / security / redis_client
│   ├── exceptions/  # 业务异常 + 全局处理器 + ExceptionHandlerMiddleware
│   ├── cache/       # 可降级通用缓存
│   └── rate_limit/  # 可降级限流
├── middleware/    # monitoring / rate_limit / rbac（权限校验依赖）
├── models/        # ORM 模型（在 models/__init__.py 汇总导出）
├── repositories/  # 数据访问层
├── schemas/       # Pydantic 入/出参
├── services/      # 业务逻辑层
├── database.py    # 引擎 + get_db（路由）/ get_session（路由外）/ ensure_database_exists
├── dependencies.py
└── main.py        # 入口：中间件注册、异常处理器、lifespan
```

## 启动
```bash
python run.py --env 1   # 开发（.env.development），热重载
python run.py --env 2   # 测试（.env.test）
python run.py --env 3   # 生产（.env）
python run.py --env 3 --prod   # 生产 + 多 worker
```

## 配置（定义在 `app/core/config.py` 的 `Settings`，新增字段须同步 `.env.example`）
- `SECRET_KEY` 必须从环境变量设置，禁止占位值。
- `DB_AUTO_CREATE`（生产置 False，走 alembic）、`DB_AUTO_CREATE_DATABASE`（启动时缺库则自动建）。
- `REDIS_URL`（空=纯内存）、`RATE_LIMIT_FALLBACK` / `CACHE_FALLBACK`。
- `ADMIN_PASSWORD`（空=首启随机生成、日志只提示一次；配置则不写日志）。
- `LOG_PROFILE=dev|prod`（dev=DEBUG+彩色控制台；prod=INFO+JSON+文件轮转）。
- `AUTH_ENABLED`（False=全局放行为超级用户，仅本地开发；DEBUG=False 时置 False 会拒绝启动）。
- `OTEL_ENABLED`（可观测性，默认 False=no-op）、`OTEL_EXPORTER_OTLP_ENDPOINT`（OTLP collector；空+启用=降级控制台）、`OTEL_TRACES_SAMPLER_RATIO`。启用后自动埋点 FastAPI/SQLAlchemy/Redis，traces+metrics 经 OTLP 导出。

## 运维端点（无版本前缀，根路径挂载）
- `/health` liveness（浅检查，进程存活）；`/readyz` readiness（探 DB，不通返回 503）。
- `/metrics/json` 手搓内存指标（单实例速览）；分布式监控用 OTel（OTLP 导出，含延迟分位数）。
- `/status` 应用各组件状态明细。

## 数据库迁移
- 单一 baseline；改模型后 `alembic revision --autogenerate -m "..."` → `alembic upgrade head`。
- 生产用 alembic 管 schema，不要同时开 `create_all` 形成双轨。

## 禁止事项
- 禁止前端渲染：Jinja2 / StaticFiles / HTMLResponse。
- 禁止 sqlite 作生产库（仅 PostgreSQL）。
- 禁止直接 `print` 或直接配置 loguru handler（用 `get_logger`）。
- 禁止提交 `*.db`、`logs/`、`.env`。

## 测试
- `python -m pytest`；目录镜像 `app/` 结构（见 `tests/README.md`）。
- `pytest.ini` 段名必须 `[pytest]`；`asyncio_mode=auto`，异步测试直接 `async def`，不要 `@pytest.mark.asyncio`。
