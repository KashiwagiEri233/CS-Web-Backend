# 运行基础设施（可观测 / 数据 / 会话）

> 本文件合并了原 `docs/observability.md` 与 `docs/data_and_tasks.md`，统一阐述应用**运行期的基础设施**：
> 如何被观察（日志/追踪/指标）、数据如何存取（数据库/事务）、应用如何启停（生命周期）、
> 后台任务如何执行（队列）、缓存如何降级。

---

## 一、可观测性

### 1.1 结构化日志（loguru）

#### 概述

`app/core/loguru_logger/` 统一封装 Loguru、标准库 logging 拦截、请求上下文和环境化输出。
业务代码只使用 `get_logger()`，不直接添加 handler。

代码：`app/core/loguru_logger/`（adapter / config / context / intercept / init 拆分）。

#### 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `init_logging` | `init_logging(settings)` | 幂等初始化日志 sink |
| `get_logger` | `get_logger(name=None) -> LoguruAdapter` | 获取带模块名的适配器 |
| `set_logging_context` | `set_logging_context(**fields)` | 绑定请求级字段 |
| `reset_logging_context` | `reset_logging_context(token)` | 恢复上下文 |
| `get_logging_context` | `get_logging_context() -> dict` | 读取当前上下文副本 |

#### 配置

`LOG_PROFILE=dev|prod` 决定默认级别、JSON、控制台与文件输出；`LOG_LEVEL`、`LOG_DIR`、
`LOG_ROTATION`、`LOG_RETENTION` 等可覆盖 profile。

#### 降级与不变量

- 日志上下文用 `ContextVar`，请求结束必须 reset，避免跨请求污染。
- `request_id`、`user_id` 等结构化字段写入 Loguru `extra`，不只拼到消息文本。
- 密码、token、数据库连接口令和客户端原始校验输入不得写入日志。
- 日志展示按 `TIMEZONE` 转换，存储和业务时间仍用 UTC。

#### 测试

`tests/core/test_structured_logging.py`、`test_exception_logging.py`、`test_exception_middleware.py`。

#### 扩展指引

新增公共字段放入请求上下文；新增 sink/格式只改日志初始化模块，禁止在业务模块直接配置 Loguru。

### 1.2 分布式追踪与指标（OpenTelemetry）

#### 概述

基于 OpenTelemetry 的 traces + metrics 接入，经 OTLP 导出到 collector（Jaeger / Tempo /
otel-collector 等）。**默认关闭**：`OTEL_ENABLED=False` 时完全 no-op；启用但未配 endpoint
时降级控制台导出；依赖缺失或埋点失败只记日志、不阻断启动。

**不负责**：人读的单实例速览指标——那是 `/metrics/json`（手搓内存版）的职责。

代码：`app/core/observability.py`；装配点：`app/main.py`（`setup_telemetry` / `shutdown_telemetry`）。

#### 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `setup_telemetry` | `setup_telemetry(app, engine) -> None` | 装配 OTel；`main.py` 创建 app 后调用一次。未启用时立即返回 |
| `shutdown_telemetry` | `shutdown_telemetry() -> None` | flush 并释放 providers；lifespan 关闭段调用。未启用时 no-op |

**运维端点（根路径，无 `/api/v1` 前缀）**

| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | liveness 浅检查，仅表示进程存活，供 k8s `livenessProbe` |
| GET | `/readyz` | 公开 readiness，仅返回 `ready/not_ready`；不通返回 **503** |
| GET | `/metrics/json` | 需超级用户；单实例内存指标 JSON（非 Prometheus 格式） |
| GET | `/status` | 需超级用户；应用各组件状态明细 |

> 标准 OTel 指标不走 HTTP 端点，而是经 OTLP **推送**到 collector，再由 Grafana 等消费。

#### 配置

| 字段 | 默认 | 说明 |
|---|---|---|
| `OTEL_ENABLED` | `False` | 总开关。False = 完全 no-op |
| `OTEL_SERVICE_NAME` | `fastapi-rbac-framework` | trace 里的 `service.name` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `None` | OTLP collector 端点（如 `http://localhost:4317`）。空 + 启用 = 降级控制台 |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` 或 `http/protobuf` |
| `OTEL_TRACES_SAMPLER_RATIO` | `1.0` | 采样率 0.0~1.0；生产高流量调小 |
| `OTEL_CONSOLE_EXPORT` | `False` | 强制控制台导出（本地调试，优先于 OTLP） |

#### 埋点范围

| 目标 | instrumentor | 产出 |
|---|---|---|
| FastAPI | `FastAPIInstrumentor.instrument_app(app)` | HTTP server span + `http.server.*` 指标（含延迟直方图 → p95/p99） |
| SQLAlchemy | `SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)` | DB 查询 span（含 SQL） |
| Redis | `RedisInstrumentor().instrument()` | 缓存/限流 Redis 调用 span |

> 刻意**不**接 asyncpg instrumentor，避免与 SQLAlchemy span 重复嵌套。

#### 启用步骤

1. 起 collector（如 Jaeger all-in-one）：`docker run --rm -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one:latest`
2. 配置：`OTEL_ENABLED=True`、`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`、`OTEL_EXPORTER_OTLP_PROTOCOL=grpc`
3. 启动服务，访问接口，到 Jaeger UI 按 `service.name` 查 trace
4. 延迟分位数：Prometheus/Grafana 对 `http.server.duration` 用 `histogram_quantile(0.95, ...)`

本地无 collector：设 `OTEL_ENABLED=True` + `OTEL_CONSOLE_EXPORT=True`。

#### 降级与不变量

- **总开关优先**：`OTEL_ENABLED=False` → 一行不执行。
- **不阻断启动**：SDK 依赖缺失、OTLP exporter 缺失、单项埋点失败均只记日志后继续。
- **未配 endpoint 不报错**：自动降级控制台导出并 `warning`。
- **关闭要 flush**：`shutdown_telemetry()` 刷出 BatchSpanProcessor 缓冲。

#### 测试与扩展

- 测试：默认关闭，单测不依赖；启用冒烟见 §1.2。
- 扩展：`_instrument_all` 加 try/except 调用新 instrumentor；自定义业务 span 用 `trace.get_tracer(__name__)`；多 worker 各自装配 provider。

---

## 二、数据库与事务

### 概述

`app/database.py` 提供 PostgreSQL 异步引擎、会话工厂、请求/非请求会话入口，以及 Alembic 启动校验。
全环境 schema 唯一来源是 Alembic，禁止 `create_all`。

### 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_db` | `async generator[AsyncSession]` | FastAPI 请求依赖 |
| `get_session` | `async context manager[AsyncSession]` | worker、脚本和后台任务 |
| `ensure_database_exists` | `await ensure_database_exists() -> bool` | 可选创建目标库 |
| `startup_database` | lifecycle startup task | 迁移/版本校验和连通性探测 |

### 配置

`DATABASE_URL` 或 host/port/name/user/password 组装；连接池 `DB_POOL_*`；`DB_AUTO_CREATE_DATABASE` 控制建库；
`DB_AUTO_MIGRATE` 控制自动 upgrade，否则只校验 revision 与 head 一致。

### 事务与不变量

- Repository 只 `flush`，Service 显式 `commit`。
- 请求外会话异常自动 rollback，但不自动 commit。
- 组合业务调用 Service 用 `commit=False`，最外层一次提交。
- 多 worker 自动迁移和 RBAC seed 用 PostgreSQL advisory lock。
- 模型时间列统一 `DateTime(timezone=True)`。

### 测试

- CI：`upgrade head → downgrade base → upgrade head`。
- `tests/integration/test_http_postgres_e2e.py`、`test_auth_token_lifecycle.py`、`test_rbac_db.py`。

### 扩展指引

修改模型后新增增量迁移，检查单一 head；不得修改历史迁移或调用 `Base.metadata.create_all`。

---

## 三、启动 / 关闭任务注册表（lifecycle）

### 概述

把应用启动/关闭初始化逻辑从 `main.py` 解耦：各模块用 `@register_startup` / `@register_shutdown` 自注册，
`lifespan` 只调 `run_startup()` / `run_shutdown()` 遍历执行。

代码：`app/core/lifecycle/`（`registry.py` + `__init__.py`）。

**运行时边界**：DB engine/Redis/OTel provider 是进程级资源，只支持"一进程一个活动应用"；`app/core/app_runtime.py` 在 lifespan 进入时取得进程所有权。

### 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `register_startup` | `register_startup(name, priority=50, critical=True)` | 登记启动任务 |
| `register_shutdown` | `register_shutdown(name, priority=50)` | 登记关闭任务 |
| `run_startup` | `await run_startup() -> None` | 按 priority **升序**执行启动任务 |
| `run_shutdown` | `await run_shutdown() -> None` | 按 priority **降序**执行关闭任务 |

协程约定：`async def task() -> None`（无参；依赖在函数体内自行获取）。

### 当前已注册任务

| 任务名 | 类型 | priority | critical | 位置 | 说明 |
|---|---|---|---|---|---|
| `database` | startup | 10 | **True** | `app/database.py` | 建库 + schema + 连通性探测；失败拒绝启动 |
| `rbac_seed` | startup | 20 | True | `app/services/rbac_init.py` | 权限/角色/默认管理员；集群锁，失败拒绝启动 |
| `redis_probe` | startup | 30 | False* | `app/core/redis_client.py` | 探测 Redis；`REQUIRE_REDIS_FOR_SECURITY=True` 时失败拒绝启动 |
| `refresh_token_gc` | startup/shutdown | 40/30 | False | `app/services/token_gc.py` | 清理过期/撤销 refresh token；集群锁 |
| `exception_log_retention` | startup/shutdown | 45/25 | False | `app/services/exception_retention.py` | 按保留期清理异常日志；集群锁 |
| `log_status` | startup | 90 | False | `app/main.py` | 输出访问地址/文档路径 |
| `telemetry` | shutdown | 10 | — | `app/core/observability.py` | flush 并释放 OTel providers |
| `redis` | shutdown | 20 | — | `app/core/redis_client.py` | 释放 Redis 连接 |

### priority 约定

| 段 | 含义 | 示例 |
|---|---|---|
| 10 | 基础设施（DB / schema） | `database` |
| 20 | 依赖基础设施的业务 seed | `rbac_seed` |
| 30 | 增强项探测 | `redis_probe` |
| 40–49 | 后台维护任务 | `refresh_token_gc`、`exception_log_retention` |
| 90 | 展示 / 收尾 | `log_status` |

### 降级与不变量

- `critical=True` 任务失败 → raise 中止启动；`critical=False` 失败 → 仅告警继续。
- 关闭阶段绝不抛错：任何关闭异常吞掉只记 warning。
- 重名保护：startup/shutdown 各自命名空间重名注册立即抛 `ValueError`。
- 执行顺序以 priority 为准，不依赖 import 顺序。

### 测试与扩展

- 测试：`tests/core/test_lifecycle.py`、`test_app_runtime.py`。
- 扩展：写协程函数 + 装饰器；`lifecycle/__init__.py` 的 `_import_registrants()` 追加 import；core 失败需拒绝启动才标 `critical=True`；需清理资源的配套 `@register_shutdown`。

**常见坑**：任务不执行 → 99% 是忘了 `_import_registrants()` import；不要在 `run_startup` 内动态注册；展示逻辑留 `lifespan`。

---

## 四、异步任务队列（arq）—— 可选模块

### 概述

把耗时操作挪到后台 worker。基于 **arq**（Redis 为 broker，复用 `REDIS_URL`）。

**可选、可删除的叶子模块**：依赖方向只有 `queue → core`；不用队列无需装 arq；关闭/未配时 `enqueue()` 就地同步执行（eager）。

代码：`app/core/queue/`（`client.py`、`tasks.py`、`worker.py`）。

### 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `enqueue` | `await enqueue(task, *args, **kwargs) -> str \| None` | 投递；真实返回 job_id，eager 就地执行返回 None |
| `close_queue_pool` | `await close_queue_pool() -> None` | 释放连接池 |
| `TASKS` | `list[Callable]` | 任务注册表（`tasks.py`） |
| `WorkerSettings` | class | arq worker 配置（`worker.py`） |

任务签名：`async def my_task(ctx, ...)`。eager 模式下 `ctx` 是最小字典，用 `ctx.get(...)` 取值。

### 配置与行为

`QUEUE_ENABLED`（默认 `False`）由队列模块自己读取（不在核心 `Settings`）；真实环境变量优先，缺失回退 `.env`。broker 复用 `settings.REDIS_URL`。

| 场景 | enqueue 行为 |
|---|---|
| `QUEUE_ENABLED=False`（默认） | eager：就地 `await` 执行 |
| `True` 但未配 `REDIS_URL` / 未装 arq / 连接失败 | eager（降级，记日志不报错） |
| `True` + `REDIS_URL` + arq 已装 | 真正投递到 broker，worker 异步执行 |

### 启用 / 停用

启用：装 `requirements-queue.txt` → 配 `QUEUE_ENABLED=True` + `REDIS_URL` → 起 worker（`arq app.core.queue.worker.WorkerSettings`）→ web 侧 `enqueue`。

停用：`QUEUE_ENABLED=False`（eager）；彻底移除 = 删 `app/core/queue/` + `requirements-queue.txt` + 业务侧 import 点（开关不在 Settings，无需改 config.py / main.py）。

### 降级与不变量

- 新任务必须登记 `tasks.TASKS`，否则 `enqueue` 抛 `ValueError`。
- 任务必须幂等可重试（worker 崩溃可能重投）。
- worker 自管 DB 会话：任务内 `async with get_session() as db:`。
- eager ≠ 真实环境；上线前用真实 Redis + worker 验证。

### 测试与扩展

- 测试：`tests/core/test_queue.py`、`tests/integration/test_queue_worker.py`。
- 扩展：加任务 `tasks.py` 登记 `TASKS`；定时任务加 `cron_jobs`；重试/超时配 `max_tries`/`job_timeout`。

---

## 五、缓存

### 概述

`app/core/cache/` 提供异步键值缓存。配置 Redis 用共享后端；未配置或故障按 `CACHE_FALLBACK` 降级到进程内缓存。

### 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_cache` | `get_cache() -> DegradableCache` | 获取进程级缓存门面 |
| `DegradableCache.get` | `await get(key)` | 读取并反序列化值 |
| `DegradableCache.set` | `await set(key, value, ttl=None)` | 写入值和可选 TTL |
| `DegradableCache.delete` | `await delete(key)` | 删除键 |
| `cached` | `@cached(ttl, key_prefix)` | 缓存异步函数结果 |

### 配置

| 配置 | 默认 | 说明 |
|---|---:|---|
| `REDIS_URL` | 空 | 空时使用内存后端 |
| `CACHE_FALLBACK` | `memory` | Redis 故障后使用 `memory` 或 `off` |
| `RATE_LIMIT_REDIS_RETRY_INTERVAL` | `5.0` | 熔断后尝试恢复 Redis 的秒数（与限流共用） |

> 内存缓存容量上限在代码中硬编码（`app/core/cache/backends.py` `_DEFAULT_MAX_ENTRIES = 10000`），**不可配置**。

### 降级与不变量

- Redis 写失败进入降级态；冷却期满半开探测，成功后恢复。
- 内存缓存不跨 worker 共享，不能用于需要全局一致性的状态。
- 缓存只能提升性能，业务正确性不能依赖缓存命中。

### 测试与扩展

- 测试：`tests/core/test_cache.py`、`tests/integration/test_redis_backends.py`。
- 扩展：新增缓存场景优先复用 `get_cache()`；键必须带业务前缀，可失效数据设 TTL。
