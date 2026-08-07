# 运行基础设施（可观测 / 数据 / 会话）（BackDoc-Infra）

> 更新人：3yearsZ
> 最后更新：2026-08-05（统一 BackDoc 命名）
> 关联：架构见 [BackDoc-01-Arch.md](BackDoc-01-Arch.md)；安全见 [BackDoc-02-Sec.md](BackDoc-02-Sec.md)；迁移验证见本文 §六
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

`tools/tests/core/test_structured_logging.py`、`test_exception_logging.py`、`test_exception_middleware.py`。

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
- `tools/tests/integration/test_http_postgres_e2e.py`、`test_auth_token_lifecycle.py`、`test_rbac_db.py`。

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

- 测试：`tools/tests/core/test_lifecycle.py`、`test_app_runtime.py`。
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

- 测试：`tools/tests/core/test_queue.py`、`tools/tests/integration/test_queue_worker.py`。
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

- 测试：`tools/tests/core/test_cache.py`、`tools/tests/integration/test_redis_backends.py`。
- 扩展：新增缓存场景优先复用 `get_cache()`；键必须带业务前缀，可失效数据设 TTL。

---

## 六、迁移验证（MIGRATION_VERIFICATION）

> **合并说明**：本章原位于 `BackDoc-MigV.md`（迁移验证指南），于 2026-08-07 并入本文 §六，与 §二 数据库与事务的迁移/版本校验形成完整闭环。
> 更新人：3yearsZ
> 最后更新：2026-08-05（统一 BackDoc 命名）
> 关联：架构见 [BackDoc-01-Arch.md](BackDoc-01-Arch.md)；安全见 [BackDoc-02-Sec.md](BackDoc-02-Sec.md)
> 执行者：Linux 环境的 agent（或任何具备 PostgreSQL 的 CI/开发机）
> 目的：验证 `d1e2f3a4b5c6_add_cs_business_tables.py`（Phase 0 数据层基线，离线手写）与 `f6a7b8c9d0e1_add_refresh_tokens_device_info.py`（Phase 1 会话字段）是否与 SQLAlchemy 模型元数据一致、能否正常升级/回滚；并跑通 Phase 1 认证全流程测试。
> 生成背景：迁移文件生成时开发机无 PostgreSQL 实例，无法 autogenerate，因此手写并需本验证。

### 6.1 预期结果摘要

| 检查项 | 预期 |
|---|---|
| `alembic heads` | 单一 head：`d6e7f8g9h0i1` |
| `alembic upgrade head` | 成功；42 张表建成（框架 8 + 业务 34，含 two_factor_auth） |
| `alembic check` | 无 drift（模型 ↔ 数据库一致） |
| `alembic downgrade -1 && upgrade head` | 往返成功 |
| Phase 1 集成测试 | `tools/tests/integration/test_auth_phase1.py` 全绿（注册/2FA/懒升级/会话/重置流） |
| pytest | 全绿（除标记 integration 且无 Redis 时跳过的用例） |

### 6.2 准备环境

```bash
# 1. 启动 PostgreSQL（以下任一方式）
# 方式 A：Docker
docker run -d --name pg-domefff -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=<你的密码> \
  -e POSTGRES_DB=domefff -p 5432:5432 postgres:16
# 方式 B：系统包
sudo apt install postgresql
sudo -u postgres psql -c "CREATE USER postgres SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE domefff OWNER postgres;"

# 2. 配置环境
cd CS-Web-Backend
cp .env.development .env          # 或 .env.local
# 修改 .env：DATABASE_PASSWORD=<你的密码>、SECRET_KEY=<>=32 字节随机串、ADMIN_PASSWORD

# 3. 安装依赖
uv sync                            # 或 pip install --require-hashes -r requirements.lock
```

> 测试库另需：库名必须含 `test`（见 `tools/tests/conftest.py` 校验），如
> `CREATE DATABASE domefff_test OWNER postgres;`

### 6.3 验证步骤

#### 6.3.1 迁移链完整性

```bash
uv run alembic heads          # 必须只有一行：d6e7f8g9h0i1 (head)
uv run alembic history | head -12
```

#### 6.3.2 升级到 head

```bash
uv run alembic upgrade head
```

预期成功。若报错，先看是否旧库残留：`alembic stamp head`（无版本表时）或 drop 库重建。

#### 6.3.3 模型 ↔ 数据库 drift 检查（关键）

```bash
uv run alembic check
```

- 输出 `No new upgrade operations detected` → 一致 ✅
- 输出差异 → **不要直接改模型**，把差异贴回迁移文件维护者：迁移文件与模型元数据不一致，需要修 `d1e2f3a4b5c6` / `f6a7b8c9d0e1` 的 upgrade/downgrade。

备用比对法（会生成临时 revision，验证后删除）：

```bash
uv run alembic revision --autogenerate -m "verify_drift"
# 打开生成的迁移文件：upgrade() 应为空或仅注释；若非空即 drift
uv run alembic downgrade -1   # 撤销该空迁移
rm alembic/versions/<新文件>   # 删除临时文件
```

#### 6.3.4 Phase 1 集成测试（认证全流程）

```bash
# 需要 domefff_test 测试库（库名含 test，见 conftest 校验）+ .env.test 的
# TOTP_ENCRYPTION_KEY/PASSWORD_RESET_DEFAULT（模板已含）
uv run python -m pytest tools/tests/integration/test_auth_phase1.py -v --no-cov
```

覆盖：注册→登录→改密、2FA 全流程（setup/confirm/登录二次验证/备用码一次性）、scrypt 懒升级、登录历史、设备列表/远程登出、忘记密码→批准→默认密码登录、验证码一次性。

#### 6.3.5 Phase 2 集成测试（公告/通知/入社/管理员用户）

```bash
uv run python -m pytest tools/tests/integration/test_phase2_modules.py -v --no-cov
```

覆盖：公告生命周期（生效/过期/角色定向/CRUD）、通知列表/已读/广播/群发记录聚合、入社提交（游客+登录）与审批（含通知与重复审批拒绝）、管理员保护规则（SELF_DISABLE/ROOT_PROTECTED/FORBIDDEN/LAST_ADMIN/NO_CHANGE）、注册→欢迎通知事件。

#### 6.3.6 子阶段 2.5 集成测试（管理员角色/审计删除）

```bash
uv run python -m pytest tools/tests/integration/test_phase2_5_admin.py -v --no-cov
```

覆盖：角色 CRUD（权限自动创建/全量替换/用户数）、系统角色删除保护、审计日志删除（单条 + 批量）。

#### 6.3.7 Phase 3 集成测试（活动模块）

```bash
uv run python -m pytest tools/tests/integration/test_phase3_events.py -v --no-cov
```

覆盖：活动 CRUD + 自动归档、报名流（重复 409/名额满 409/取消重报）、签到码生成与核销（无效码/重复使用）、批量更新 + 统计、活动设置读写/重置。

#### 6.3.8 Phase 4 集成测试（社区模块）

```bash
uv run python -m pytest tools/tests/integration/test_phase4_community.py -v --no-cov
```

覆盖：版块+主题（slug 冲突/反范式计数/浏览去重）、回复+互动（楼中楼/点赞收藏）、审核（隐藏/恢复/置顶/加精/硬删除）、社区（slug 唯一/发布/归档/点赞/系列）、成员与 Feed 聚合（标签筛选/三源合并/统计）。

#### 6.3.9 Phase 5 集成测试（工具集模块）

```bash
uv run python -m pytest tools/tests/integration/test_phase5_tools.py -v --no-cov
```

覆盖：考试（组卷/答题判分 upsert/排名/状态机）、资源（提交/审核/浏览）、任务+积分（认领限额/提交/审核→积分/流水/排行榜/等级）、Auxilio（薄弱标签+资源推荐）、组件注册表（slug 冲突/variants 四元组唯一/guide/toggle）。

> 纯单元测试（TOTP RFC 6238 向量、加密交叉验证、scrypt 兼容）已在本机通过，无需 PG：`tools/tests/core/test_totp*.py`、`tools/tests/core/test_password_compat.py`。

#### 6.3.10 前后端联调（Phase 1 BFF 切换）

前端已转换为薄转发（19 个路由，JWT 存 BFF HttpOnly Cookie + 401 静默刷新）。后端可运行后联调：

```bash
# 1. 起后端（本仓库）
uv run python run.py --env 1        # http://localhost:9000（SITE_URL 指向 BFF）
# 2. 起前端（CS-Web-Frontend，BACKEND_URL 指向后端）
cp .env.example .env
# .env: BACKEND_URL=http://localhost:9000
pnpm dev                            # http://localhost:2333
```

验证清单：

> ℹ️ 变更记录/待办条目已迁移至 `docs/项目演变历史.md` / `docs/项目待办事项.md`。

#### 6.3.11 表结构与约束抽查

```sql
-- 表清单（应为 42 张业务/框架表 + alembic_version）
\dt

-- 唯一约束抽查
\d settings          -- 应有 ux_settings_module_key (module, key)
\d event_registrations -- 应有 ux_event_registrations_unique (user_id, event_id)
\d two_factor_auth   -- 应有 fk_two_factor_auth_user_id_users (ON DELETE CASCADE)

-- partial unique index（社区浏览去重）
\d community_topic_views -- 应有 idx_community_topic_views_unique_user / _ip（WHERE 子句）

-- 循环外键（community_topics.last_reply_id -> community_replies）
\d community_topics      -- 应有 fk_community_topics_last_reply_id_community_replies

-- users 业务字段
\d users             -- display_name/bio/avatar_url/avatar_type/github_url/website_url/github_id/tech_tags

-- refresh_tokens 设备字段（Phase 1）
\d refresh_tokens    -- 应有 ip_address / user_agent

-- JSONB 列
\d exam_attempts     -- answer 为 text；tech_tags 类列应为 jsonb
```

#### 6.3.12 约束生效冒烟（可选但推荐）

```bash
uv run python - <<'PY'
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+asyncpg"))
    async with engine.connect() as conn:
        # 唯一约束：重复 (module,key) 应报 UniqueViolation
        await conn.execute(text("INSERT INTO settings(module, key, value) VALUES ('m','k','v')"))
        try:
            await conn.execute(text("INSERT INTO settings(module, key, value) VALUES ('m','k','v2')"))
            print("FAIL: unique constraint not enforced")
        except Exception as e:
            print("OK unique:", type(e).__name__)
        await conn.rollback()
        # 外键：指向不存在的用户应报错
        try:
            await conn.execute(text("INSERT INTO login_history(user_id, success) VALUES (999999, true)"))
            print("FAIL: FK not enforced")
        except Exception as e:
            print("OK fk:", type(e).__name__)
        await conn.rollback()
    await engine.dispose()

asyncio.run(main())
PY
```

#### 6.3.13 回滚往返

```bash
uv run alembic downgrade -1       # 回滚到 f0a1b2c3d4e5；再升级回 head 应无 drift
uv run alembic upgrade head       # 再升级回 head
```

#### 6.3.14 测试套件

```bash
# 需要 domefff_test 测试库（库名含 test）；Redis 缺失时限流/缓存自动降级
uv run python -m pytest -x -q --no-cov
# 或仅跑模型无关的单元测试：
uv run python -m pytest -x -q --no-cov -m "not integration"
```

### 6.4 已知约定（比对时留意，勿当 drift 误报）

| 项 | 说明 |
|---|---|
| `avatar_type` 两段式 | 迁移先加 `server_default='initial'` 再 DROP DEFAULT：存量行可写且元数据无默认值 |
| Python 侧默认值 | 所有列默认值在模型 Python 侧（`default=...`），DDL 无 `DEFAULT` 属预期 |
| JSONB | `JSONDict = JSON().with_variant(JSONB(), "postgresql")`，PG 落成 JSONB |
| 主键自增 | Integer PK 落成 SERIAL，无独立序列对象 |
| FTS5 / tsvector | 社区全文搜索不在本迁移范围（Phase 4 单独处理） |
| 索引名 | 单列 `ix_<table>_<col>`，复合/partial 用显式名（`idx_*` / `ux_*`） |

### 6.5 验证后回报（回到迁移维护者）

1. `alembic heads` / `alembic check` 输出原文
2. 冒烟脚本各断言结果（OK/FAIL）
3. `alembic upgrade head` 耗时与日志尾部
4. 如有 drift：autogenerate 差异内容
5. pytest 汇总行（passed/skipped）
