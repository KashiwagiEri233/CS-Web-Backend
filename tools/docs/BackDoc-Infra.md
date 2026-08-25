# BackDoc-Infra：后端运行基础设施参考（Reference · 可观测/数据/会话/队列/缓存的权威定义）

> 更新人：3yearsZ
> 更新日：2026-08-20
> 版本：1.0.1 · 七夕（Diátaxis R 类样板，统一参考类文档规范）
> Diátaxis：R（Reference · 回答「是什么」，提供组件接口、配置项、不变量的精确权威定义；不包含可执行步骤）
> 适用读者：后端开发者 / 运维 / SRE；已完成 Onboarding 并了解后端架构
> 变更触发：基础设施组件变更 / 新增依赖 / 配置项调整 / 接口签名修改

> **SSOT 分工声明**：
> - 本文档是「**后端运行期基础设施（可观测/数据/会话/队列/缓存）的接口定义、配置表、不变量**」的唯一权威（SSOT）。
> - 基础设施使用方法（部署、启用、调试）→ [RootDoc-Deploy.md](../../../docs/RootDoc-Deploy.md)（How-to）。
> - 迁移验证步骤（可执行的验证流程）→ 本文档 **附录 A**（从原 §六 降级为参考附录，完整 How-to 部署流程见 Deploy 文档）。
> - 架构总览（模块依赖、运行时序列）→ [BackDoc-01-Arch.md](BackDoc-01-Arch.md)（Arc42）。
> - 安全红线（密钥、凭证、加密）→ [BackDoc-02-Sec.md](BackDoc-02-Sec.md)。
> - 工程约定（DDD 分层、Repository 规范）→ [BackDoc-03-Conv.md](BackDoc-03-Conv.md)。

> **文档结构**：本文档按「组件」组织，每个组件独立成节。每节包含：
> 1. **概述**：该组件的职责与边界
> 2. **接口定义表**：公开 API 的精确签名与用途
> 3. **配置项表**：环境变量、默认值、影响范围
> 4. **不变量与约束**：RFC 2119 关键词标记的硬性约束与降级策略
> 5. **测试覆盖**：单元/集成测试文件路径

---

## 快速索引

| 组件 | 概述 | 接口表 | 配置表 | 不变量 | 测试 | 代码位置 |
|---|---|---|---|---|---|---|
| **§1 结构化日志（loguru）** | 日志封装与上下文 | §1.2 | §1.3 | §1.4 | §1.5 | `app/core/loguru_logger/` |
| **§2 分布式追踪与指标（OTel）** | traces + metrics 接入 | §2.2 | §2.3 | §2.4 | §2.5 | `app/core/observability.py` |
| **§3 数据库与事务** | PG 异步引擎与会话 | §3.2 | §3.3 | §3.4 | §3.5 | `app/database.py` |
| **§4 生命周期注册表** | 启停任务自注册 | §4.2 | §4.3 | §4.4 | §4.5 | `app/core/lifecycle/` |
| **§5 异步任务队列（arq）** | 可选后台 worker | §5.2 | §5.3 | §5.4 | §5.5 | `app/core/queue/` |
| **§6 缓存** | 可降级键值缓存 | §6.2 | §6.3 | §6.4 | §6.5 | `app/core/cache/` |
| **附录 A：迁移验证参考** | Alembic 验证命令速查 | — | — | — | — | `alembic/versions/` |

---

## §1 结构化日志（loguru）

### 1.1 概述

`app/core/loguru_logger/` 统一封装 Loguru、标准库 logging 拦截、请求上下文和环境化输出。业务代码只使用 `get_logger()`，**MUST NOT** 直接添加 handler。

### 1.2 接口定义表

| 符号 | 签名 | 用途 |
|---|---|---|
| `init_logging` | `init_logging(settings)` | 幂等初始化日志 sink |
| `get_logger` | `get_logger(name=None) -> LoguruAdapter` | 获取带模块名的适配器 |
| `set_logging_context` | `set_logging_context(**fields)` | 绑定请求级字段 |
| `reset_logging_context` | `reset_logging_context(token)` | 恢复上下文 |
| `get_logging_context` | `get_logging_context() -> dict` | 读取当前上下文副本 |

### 1.3 配置项表

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOG_PROFILE` | `dev` | `dev` → 控制台彩色输出；`prod` → JSON + 文件输出 |
| `LOG_LEVEL` | `INFO` | 覆盖 profile 默认级别（DEBUG/INFO/WARNING/ERROR/CRITICAL） |
| `LOG_DIR` | `logs/` | 日志文件输出目录（prod profile） |
| `LOG_ROTATION` | `10 MB` | 日志文件大小阈值（prod profile） |
| `LOG_RETENTION` | `30 days` | 日志保留期（prod profile） |

### 1.4 不变量与约束（RFC 2119）

| 等级 | 约束 |
|---|---|
| **MUST** | 请求日志上下文用 `ContextVar`，请求结束 **MUST** reset，避免跨请求污染 |
| **MUST** | `request_id`、`user_id` 等结构化字段写入 Loguru `extra`，**MUST NOT** 仅拼接到消息文本 |
| **MUST NOT** | 密码、token、数据库连接口令、客户端原始校验输入 **MUST NOT** 写入日志 |
| **SHOULD** | 日志展示按 `TIMEZONE` 转换，存储和业务时间 **SHOULD** 用 UTC |
| **MUST NOT** | 业务模块 **MUST NOT** 直接配置 Loguru sink/格式；新增 sink/格式只改日志初始化模块 |

### 1.5 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/core/test_structured_logging.py` | 结构化日志上下文绑定 |
| `tools/tests/core/test_exception_logging.py` | 异常日志格式 |
| `tools/tests/core/test_exception_middleware.py` | 中间件日志拦截 |

---

## §2 分布式追踪与指标（OpenTelemetry）

### 2.1 概述

基于 OpenTelemetry 的 traces + metrics 接入，经 OTLP 导出到 collector（Jaeger / Tempo / otel-collector 等）。**默认关闭**：`OTEL_ENABLED=False` 时完全 no-op；启用但未配 endpoint 时降级控制台导出；依赖缺失或埋点失败只记日志、不阻断启动。

**不负责**：人读的单实例速览指标 — 那是 `/metrics/json`（手搓内存版）的职责。

### 2.2 接口定义表

**OTel 装配接口**

| 符号 | 签名 | 用途 |
|---|---|---|
| `setup_telemetry` | `setup_telemetry(app, engine) -> None` | 装配 OTel；`main.py` 创建 app 后调用一次。未启用时立即返回 |
| `shutdown_telemetry` | `shutdown_telemetry() -> None` | flush 并释放 providers；lifespan 关闭段调用。未启用时 no-op |

**运维端点（根路径，无 `/api/v1` 前缀）**

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/health` | 无 | liveness 浅检查，仅表示进程存活，供 k8s `livenessProbe` |
| GET | `/readyz` | 无 | readiness 深检查，返回 `ready/not_ready`；不通返回 **503** |
| GET | `/metrics/json` | 超级用户 | 单实例内存指标 JSON（非 Prometheus 格式） |
| GET | `/status` | 超级用户 | 应用各组件状态明细 |
| GET | `/health/events` | 无 | 事件总线各监听器数量，供运维定位事件链路 |
| GET | `/health/security` | 无 | 限流/会话/迁移等安全组件状态 |

> 标准 OTel 指标不走 HTTP 端点，而是经 OTLP **推送**到 collector，再由 Grafana 等消费。

### 2.3 配置项表

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OTEL_ENABLED` | `False` | 总开关。False = 完全 no-op |
| `OTEL_SERVICE_NAME` | `fastapi-rbac-framework` | trace 里的 `service.name` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `None` | OTLP collector 端点（如 `http://localhost:4317`）。空 + 启用 = 降级控制台 |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` 或 `http/protobuf` |
| `OTEL_TRACES_SAMPLER_RATIO` | `1.0` | 采样率 0.0~1.0；生产高流量调小 |
| `OTEL_CONSOLE_EXPORT` | `False` | 强制控制台导出（本地调试，优先于 OTLP） |

**埋点范围**

| 目标 | instrumentor | 产出 |
|---|---|---|
| FastAPI | `FastAPIInstrumentor.instrument_app(app)` | HTTP server span + `http.server.*` 指标（含延迟直方图 → p95/p99） |
| SQLAlchemy | `SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)` | DB 查询 span（含 SQL） |
| Redis | `RedisInstrumentor().instrument()` | 缓存/限流 Redis 调用 span |

> 刻意**不**接 asyncpg instrumentor，避免与 SQLAlchemy span 重复嵌套。

### 2.4 不变量与约束（RFC 2119）

| 等级 | 约束 |
|---|---|
| **MUST** | `OTEL_ENABLED=False` → 一行不执行（总开关优先） |
| **MUST NOT** | SDK 依赖缺失、OTLP exporter 缺失、单项埋点失败 **MUST NOT** 阻断启动 |
| **MUST** | 未配 endpoint **MUST** 自动降级控制台导出并 `warning` |
| **MUST** | `shutdown_telemetry()` **MUST** flush BatchSpanProcessor 缓冲后释放 providers |
| **MUST NOT** | asyncpg instrumentor **MUST NOT** 接入（避免与 SQLAlchemy span 重复嵌套） |
| **SHOULD** | 生产环境 `OTEL_TRACES_SAMPLER_RATIO` **SHOULD** 根据流量调小（如 0.1~0.5） |

### 2.5 测试覆盖

默认关闭，单测不依赖；启用冒烟见 [RootDoc-Deploy.md](../../../docs/RootDoc-Deploy.md) 场景 A。

---

## §3 数据库与事务

### 3.1 概述

`app/database.py` 提供 PostgreSQL 异步引擎、会话工厂、请求/非请求会话入口，以及 Alembic 启动校验。全环境 schema 唯一来源是 Alembic，**MUST NOT** 使用 `create_all`。

### 3.2 接口定义表

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_db` | `async generator[AsyncSession]` | FastAPI 请求依赖 |
| `get_session` | `async context manager[AsyncSession]` | worker、脚本和后台任务 |
| `ensure_database_exists` | `await ensure_database_exists() -> bool` | 可选创建目标库 |
| `startup_database` | lifecycle startup task | 迁移/版本校验和连通性探测 |

### 3.3 配置项表

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 完整数据库 URL；或 `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` 组装 |
| `DB_POOL_SIZE` | 连接池大小 |
| `DB_POOL_MAX_OVERFLOW` | 连接池最大溢出 |
| `DB_AUTO_CREATE_DATABASE` | 控制建库开关 |
| `DB_AUTO_MIGRATE` | 控制自动 upgrade，否则只校验 revision 与 head 一致 |

**应用数据表（工作台/学习助手/番茄钟/LLM）**

| 表 | 用途 | 迁移 revision | 关键字段 |
|---|---|---|---|
| `contribution_cache` | 贡献/活动年度统计缓存 | `b0b1c2d3e4f5` | user_id, platform, year, data(jsonb), total, streak, fetched_at |
| `api_call_logs` | API 调用匿名埋点 | `b0b1c2d3e4f5` | user_id(恒NULL), endpoint, method, status, latency_ms, created_at |
| `conversations` | 学习助手会话 | `b0b1c2d3e4f5` | user_id, title, created_at, updated_at |
| `chat_messages` | 学习助手消息（含 tool_calls jsonb） | `b0b1c2d3e4f5` | conversation_id, role, content, tool_calls(jsonb) |
| `focus_sessions` | 番茄钟专注记录 | `c2d3e4f5a6b7` | user_id, duration_seconds, phase, sound_source, started_at |
| `llm_usage_logs` | LLM 调用用量计量 | `d3e4f5a6b7c8` | user_id, provider, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, status |
| `llm_configs` | 用户级 LLM 配置（API Key 加密） | `d3e4f5a6b7c8` | user_id(PK), provider, api_key_encrypted, base_url, model |

> 这些表与凭证无关；`users` 等用户表、token 表（`refresh_tokens`）、2FA 表（`two_factor_auth`）见各自模块与 [BackDoc-02-Sec.md](BackDoc-02-Sec.md) §1。

### 3.4 不变量与约束（RFC 2119）

| 等级 | 约束 |
|---|---|
| **MUST NOT** | Repository **MUST NOT** 自行 `commit`；仅 `flush` |
| **MUST** | Service 层显式 `commit`；请求外会话异常 **MUST** 自动 rollback，但 **MUST NOT** 自动 commit |
| **MUST** | 组合业务调用 Service 用 `commit=False`，最外层一次提交 |
| **MUST** | 多 worker 自动迁移和 RBAC seed **MUST** 使用 PostgreSQL advisory lock |
| **MUST** | 模型时间列 **MUST** 使用 `DateTime(timezone=True)` |
| **MUST NOT** | 修改模型后 **MUST NOT** 修改历史迁移或调用 `Base.metadata.create_all`；**MUST** 新增增量迁移 |
| **MUST** | 迁移链 **MUST** 保持单一 head（当前 head: `e5f6a7b8c9d0`，线性链、无分支） |

### 3.5 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/integration/test_http_postgres_e2e.py` | E2E PG 集成 |
| `tools/tests/features/auth/test_auth_token_lifecycle.py` | Token 生命周期 |
| `tools/tests/features/rbac/test_rbac_db.py` | RBAC 数据库操作 |
| CI: `upgrade head → downgrade base → upgrade head` | 迁移往返验证 |

---

## §4 启动/关闭任务注册表（lifecycle）

### 4.1 概述

把应用启动/关闭初始化逻辑从 `main.py` 解耦：各模块用 `@register_startup` / `@register_shutdown` 自注册，`lifespan` 只调 `run_startup()` / `run_shutdown()` 遍历执行。

**运行时边界**：DB engine/Redis/OTel provider 是进程级资源，只支持"一进程一个活动应用"；`app/core/app_runtime.py` 在 lifespan 进入时取得进程所有权。

### 4.2 接口定义表

| 符号 | 签名 | 用途 |
|---|---|---|
| `register_startup` | `register_startup(name, priority=50, critical=True)` | 登记启动任务 |
| `register_shutdown` | `register_shutdown(name, priority=50)` | 登记关闭任务 |
| `run_startup` | `await run_startup() -> None` | 按 priority **升序**执行启动任务 |
| `run_shutdown` | `await run_shutdown() -> None` | 按 priority **降序**执行关闭任务 |

协程约定：`async def task() -> None`（无参；依赖在函数体内自行获取）。

### 4.3 配置项表

**当前已注册任务**

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

**priority 分段约定**

| 段 | 含义 | 示例 |
|---|---|---|
| 10 | 基础设施（DB/schema） | `database` |
| 20 | 依赖基础设施的业务 seed | `rbac_seed` |
| 30 | 增强项探测 | `redis_probe` |
| 40–49 | 后台维护任务 | `refresh_token_gc`、`exception_log_retention` |
| 90 | 展示/收尾 | `log_status` |

### 4.4 不变量与约束（RFC 2119）

| 等级 | 约束 |
|---|---|
| **MUST** | `critical=True` 任务失败 **MUST** raise 中止启动；`critical=False` 失败 **MUST** 仅告警继续 |
| **MUST NOT** | 关闭阶段 **MUST NOT** 抛错：任何关闭异常吞掉只记 warning |
| **MUST** | 重名保护：startup/shutdown 各自命名空间重名注册 **MUST** 立即抛 `ValueError` |
| **MUST** | 执行顺序 **MUST** 以 priority 为准，不依赖 import 顺序 |
| **MUST NOT** | 不得在 `run_startup` 内动态注册；展示逻辑 **MUST** 留 `lifespan` 阶段 |
| **MUST** | `_import_registrants()` **MUST** 包含新注册模块（任务不执行 99% 是忘了 import） |

### 4.5 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/core/test_lifecycle.py` | 启停任务注册与执行顺序 |
| `tools/tests/core/test_app_runtime.py` | 进程所有权检测 |

---

## §5 异步任务队列（arq）

### 5.1 概述

把耗时操作挪到后台 worker。基于 **arq**（Redis 为 broker，复用 `REDIS_URL`）。

**可选、可删除的叶子模块**：依赖方向只有 `queue → core`；不用队列无需装 arq；关闭/未配时 `enqueue()` 就地同步执行（eager）。

### 5.2 接口定义表

| 符号 | 签名 | 用途 |
|---|---|---|
| `enqueue` | `await enqueue(task, *args, **kwargs) -> str \| None` | 投递；真实返回 job_id，eager 就地执行返回 None |
| `close_queue_pool` | `await close_queue_pool() -> None` | 释放连接池 |
| `TASKS` | `list[Callable]` | 任务注册表（`tasks.py`） |
| `WorkerSettings` | class | arq worker 配置（`worker.py`） |

任务签名：`async def my_task(ctx, ...)`。eager 模式下 `ctx` 是最小字典，用 `ctx.get(...)` 取值。

### 5.3 配置项表

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QUEUE_ENABLED` | `False` | 队列总开关（队列模块自己读取，不在核心 `Settings`） |
| `REDIS_URL` | 空 | broker 地址（复用 Redis 配置） |

**enqueue 行为矩阵**

| 场景 | enqueue 行为 |
|---|---|
| `QUEUE_ENABLED=False`（默认） | eager：就地 `await` 执行 |
| `True` 但未配 `REDIS_URL` / 未装 arq / 连接失败 | eager（降级，记日志不报错） |
| `True` + `REDIS_URL` + arq 已装 | 真正投递到 broker，worker 异步执行 |

### 5.4 不变量与约束（RFC 2119）

| 等级 | 约束 |
|---|---|
| **MUST** | 新任务 **MUST** 登记 `tasks.TASKS`，否则 `enqueue` 抛 `ValueError` |
| **MUST** | 任务 **MUST** 幂等可重试（worker 崩溃可能重投） |
| **MUST** | worker 自管 DB 会话：任务内 **MUST** `async with get_session() as db:` |
| **SHOULD** | `max_tries` / `job_timeout` **SHOULD** 根据任务性质配置 |
| **MUST NOT** | 上线前 **MUST NOT** 仅依赖 eager 模式；**MUST** 用真实 Redis + worker 验证 |

### 5.5 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/core/test_queue.py` | 队列核心逻辑 |
| `tools/tests/features/queue/test_queue_worker.py` | Worker 集成测试 |

---

## §6 缓存

### 6.1 概述

`app/core/cache/` 提供异步键值缓存。配置 Redis 用共享后端；未配置或故障按 `CACHE_FALLBACK` 降级到进程内缓存。

### 6.2 接口定义表

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_cache` | `get_cache() -> DegradableCache` | 获取进程级缓存门面 |
| `DegradableCache.get` | `await get(key)` | 读取并反序列化值 |
| `DegradableCache.set` | `await set(key, value, ttl=None)` | 写入值和可选 TTL |
| `DegradableCache.delete` | `await delete(key)` | 删除键 |
| `cached` | `@cached(ttl, key_prefix)` | 缓存异步函数结果 |

### 6.3 配置项表

| 变量 | 默认值 | 说明 |
|---|---|---|
| `REDIS_URL` | 空 | 空时使用内存后端 |
| `CACHE_FALLBACK` | `memory` | Redis 故障后使用 `memory` 或 `off` |
| `RATE_LIMIT_REDIS_RETRY_INTERVAL` | `5.0` | 熔断后尝试恢复 Redis 的秒数（与限流共用） |

> 内存缓存容量上限在代码中硬编码（`app/core/cache/backends.py` `_DEFAULT_MAX_ENTRIES = 10000`），**不可配置**。

### 6.4 不变量与约束（RFC 2119）

| 等级 | 约束 |
|---|---|
| **MUST** | Redis 写失败 **MUST** 进入降级态；冷却期满 **MUST** 半开探测，成功后恢复 |
| **MUST NOT** | 内存缓存不跨 worker 共享，**MUST NOT** 用于需要全局一致性的状态 |
| **MUST NOT** | 业务正确性 **MUST NOT** 依赖缓存命中；缓存只能提升性能 |
| **MUST** | 缓存键 **MUST** 带业务前缀；可失效数据 **MUST** 设 TTL |
| **SHOULD** | 新增缓存场景 **SHOULD** 优先复用 `get_cache()` 门面 |

### 6.5 测试覆盖

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/core/test_cache.py` | 缓存核心逻辑 |
| `tools/tests/integration/test_redis_backends.py` | Redis 后端集成 |

---

## 附录 A：迁移验证命令参考

> 本附录从原 BackDoc-Infra §六 降级而来，仅保留命令速查与预期结果。完整 How-to 部署流程见 [RootDoc-Deploy.md](../../../docs/RootDoc-Deploy.md)。

### A.1 迁移链完整性

```bash
uv run alembic heads                    # 必须只有一行：e5f6a7b8c9d0 (head)
uv run alembic history | head -12       # 查看迁移链
```

### A.2 升级与漂移检查

```bash
uv run alembic upgrade head             # 升级到 head
uv run alembic check                    # 模型 ↔ 数据库 drift 检查
```

**漂移检查结果解读**：
- `No new upgrade operations detected` → 一致 ✅
- 输出差异 → 迁移文件与模型元数据不一致，**不要直接改模型**，把差异贴回迁移文件维护者

### A.3 迁移往返

```bash
uv run alembic downgrade -1 && uv run alembic upgrade head   # 回滚再升级应无 drift
```

### A.4 集成测试套件

| 测试文件 | 覆盖范围 |
|---|---|
| `tools/tests/features/auth/test_auth_phase1.py` | 注册/2FA/改密/重置流 |
| `tools/tests/features/modules/test_phase2_modules.py` | 公告/通知/入社/管理员 CRUD |
| `tools/tests/features/admin/test_phase2_5_admin.py` | 管理员角色/审计删除 |
| `tools/tests/features/events/test_phase3_events.py` | 活动 CRUD/报名/签到 |
| `tools/tests/features/community/test_phase4_community.py` | 版块/主题/回复/审核 |
| `tools/tests/features/tools/test_phase5_tools.py` | 考试/资源/任务/Auxilio |

```bash
# 全量测试（需要 domefff_test 测试库 + Redis 可选）
uv run python -m pytest -x -q --no-cov
# 仅跑模型无关的单元测试
uv run python -m pytest -x -q --no-cov -m "not integration"
```

### A.5 已知约定（比对时留意，勿当 drift 误报）

| 项 | 说明 |
|---|---|
| `avatar_type` 两段式 | 迁移先加 `server_default='initial'` 再 DROP DEFAULT：存量行可写且元数据无默认值 |
| Python 侧默认值 | 所有列默认值在模型 Python 侧（`default=...`），DDL 无 `DEFAULT` 属预期 |
| JSONB | `JSONDict = JSON().with_variant(JSONB(), "postgresql")`，PG 落成 JSONB |
| 主键自增 | Integer PK 落成 SERIAL，无独立序列对象 |
| 索引名 | 单列 `ix_<table>_<col>`，复合/partial 用显式名（`idx_*` / `ux_*`） |

---

> ↩ **返回后端文档地图**：[BackDoc-01-Arch.md](BackDoc-01-Arch.md) · [BackDoc-02-Sec.md](BackDoc-02-Sec.md) · [BackDoc-03-Conv.md](BackDoc-03-Conv.md) · [BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md) · **全栈部署**：[RootDoc-Deploy.md](../../../docs/RootDoc-Deploy.md) · **工程约定**：[RootDoc-EngConv.md](../../../docs/RootDoc-EngConv.md)
