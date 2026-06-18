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
- 连接池 `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_TIMEOUT`/`DB_POOL_RECYCLE`/`DB_POOL_PRE_PING`（均有默认值，引擎在 `database.py` 由这些字段构建；生产保持 `pool_pre_ping=True`）。
- `REDIS_URL`（空=纯内存）、`RATE_LIMIT_FALLBACK` / `CACHE_FALLBACK`。
- `ADMIN_PASSWORD`（空=首启随机生成、日志只提示一次；配置则不写日志）。
- `LOG_PROFILE=dev|prod`（dev=DEBUG+彩色控制台；prod=INFO+JSON+文件轮转）。
- `AUTH_ENABLED`（False=全局放行为超级用户，仅本地开发；DEBUG=False 时置 False 会拒绝启动）。
- `OTEL_ENABLED`（可观测性，默认 False=no-op）、`OTEL_EXPORTER_OTLP_ENDPOINT`（OTLP collector；空+启用=降级控制台）、`OTEL_TRACES_SAMPLER_RATIO`。启用后自动埋点 FastAPI/SQLAlchemy/Redis，traces+metrics 经 OTLP 导出。
- 异步任务队列（arq，**可选模块**）：开关 `QUEUE_ENABLED` 由队列模块自读环境变量/.env（**不在 Settings**），默认 eager 就地执行；core 不依赖，可整建删除 `app/core/queue/`。详见 `docs/system/queue.md`。

## 时区（双时区约定：核心 UTC / 展示本地）
- **核心/存储一律 UTC**：DB 列用 `DateTime(timezone=True)`、默认值/JWT/token 过期/缓存过期全部走 `app/core/timezone.py` 的 `now_utc()`。**禁止** `datetime.now()`（naive 本地）/ `datetime.utcnow()`（naive）/ 裸 `datetime.now(timezone.utc)`——统一走 `now_utc()`，便于测试 mock。
- **展示用本地时区**：由 `settings.TIMEZONE`（IANA 名，如 `Asia/Shanghai`）控制；存储的 UTC 经 `utc_to_local()` 转换后呈现。已接入**日志层**（`init_logging` 里 `_apply_timezone_patcher`，时间戳按 TIMEZONE 显示）。
- **对外 API 出参也转本地**：出参模型继承 `app/schemas/base.py` 的 `TZModel`（带 `from_attributes`），其 `field_serializer("*")` 在序列化边界统一把 datetime 字段从 UTC 转 `settings.TIMEZONE` 并输出 ISO（带 `+08:00`）。**新增带 datetime 的响应模型必须继承 `TZModel`**，不要再手写 per-field serializer。错误响应模型（`ErrorResponse`/`ErrorContext`）同样继承 `TZModel`，故其 timestamp 也是本地时区。
- **必须装 `tzdata`**（已在 requirements.txt）：Windows / alpine / distroless 无系统 IANA 库，缺它 `ZoneInfo("Asia/Shanghai")` 会失败——展示层静默回退 UTC（差 8 小时）、且 `config._validate_timezone` 会误报"时区非法"启动失败。改非 UTC 时区前先确保已装。

## 运维端点（无版本前缀，根路径挂载）
- `/health` liveness（浅检查，进程存活）；`/readyz` readiness（探 DB+Redis，DB 不通返回 503；Redis 可降级故只报告不影响就绪）。
- `/metrics/json` 手搓内存指标（单实例速览）；分布式监控用 OTel（OTLP 导出，含延迟分位数）。
- `/status` 应用各组件状态明细。

## 分层约定
- **仓储**：继承 `app/repositories/base.py` 的 `BaseRepository[Model]`（设类属性 `model`），即得通用 `get_by_id/get_all/count/create/update/delete`；特化查询在子类追加。不要再逐个 repo 重写 CRUD。
- **列表接口**：查询参数用 `PaginationParams`（`Depends()`，`?skip=&limit=`），响应用 `PaginatedResponse[T]`（`app/schemas/pagination.py`，含 `items/total/skip/limit`），保持各列表接口结构一致。
- **出参时间**：见上「时区」——带 datetime 的响应模型继承 `TZModel`。

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
