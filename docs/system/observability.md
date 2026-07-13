# 可观测性（OpenTelemetry）

## 概述

基于 OpenTelemetry 的 traces + metrics 接入，经 OTLP 导出到 collector（Jaeger / Tempo /
otel-collector 等）。**默认关闭**，遵循项目"可降级"哲学：`OTEL_ENABLED=False` 时完全 no-op，
零运行时开销；启用但未配 endpoint 时降级为控制台导出；依赖缺失或埋点失败都只记日志、不阻断启动。

负责：分布式追踪（请求 → DB → Redis 全链路 span）与标准指标（含 HTTP 延迟直方图，可算 p95/p99）。
**不负责**：人读的单实例速览指标——那是 `/metrics/json`（手搓内存版）的职责。

代码：`app/core/observability.py`；装配点：`app/main.py`（`setup_telemetry` / `shutdown_telemetry`）。

## 接口

### 公共函数
| 符号 | 签名 | 用途 |
|---|---|---|
| `setup_telemetry` | `setup_telemetry(app, engine) -> None` | 装配 OTel；`main.py` 创建 app 后调用一次。未启用时立即返回 |
| `shutdown_telemetry` | `shutdown_telemetry() -> None` | flush 并释放 providers；在 lifespan 关闭段调用。未启用时 no-op |

### 运维端点（根路径，无 `/api/v1` 前缀）
| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | liveness 浅检查，仅表示进程存活，供 k8s `livenessProbe` |
| GET | `/readyz` | 公开 readiness，仅返回 `ready/not_ready`；不通返回 **503** |
| GET | `/metrics/json` | 需超级用户；单实例内存指标 JSON（非 Prometheus 格式） |
| GET | `/status` | 需超级用户；应用各组件状态明细 |

> 标准 OTel 指标不走 HTTP 端点，而是经 OTLP **推送**到 collector，再由 Grafana 等消费。

## 配置

`app/core/config.py` 的 `Settings`（样例见 `.env.example`）：

| 字段 | 默认 | 说明 |
|---|---|---|
| `OTEL_ENABLED` | `False` | 总开关。False = 完全 no-op |
| `OTEL_SERVICE_NAME` | `fastapi-rbac-framework` | trace 里的 `service.name` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `None` | OTLP collector 端点（如 `http://localhost:4317`）。空 + 启用 = 降级控制台 |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` 或 `http/protobuf` |
| `OTEL_TRACES_SAMPLER_RATIO` | `1.0` | 采样率 0.0~1.0；生产高流量调小（如 `0.1`） |
| `OTEL_CONSOLE_EXPORT` | `False` | 强制控制台导出（本地调试，优先于 OTLP） |

## 埋点范围

`setup_telemetry` 启用时自动埋点（各项 try/except 容错，单项失败不影响其余）：

| 目标 | instrumentor | 产出 |
|---|---|---|
| FastAPI | `FastAPIInstrumentor.instrument_app(app)` | HTTP server span + `http.server.*` 指标（含延迟直方图 → p95/p99） |
| SQLAlchemy | `SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)` | DB 查询 span（含 SQL 语句） |
| Redis | `RedisInstrumentor().instrument()` | 缓存/限流的 Redis 调用 span |

> 刻意**不**接 asyncpg instrumentor，避免与 SQLAlchemy span 重复嵌套。

## 启用步骤

1. 起一个 collector（以全家桶 all-in-one 的 Jaeger 为例）：
   ```bash
   docker run --rm -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one:latest
   ```
2. 配置环境变量（或写入 `.env`）：
   ```env
   OTEL_ENABLED=True
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
   OTEL_EXPORTER_OTLP_PROTOCOL=grpc
   ```
3. 启动服务，访问任意接口，到 Jaeger UI（http://localhost:16686）按 `service.name` 查 trace。
4. 看延迟分位数：指标接入 Prometheus/Grafana 后，对 `http.server.duration` 直方图用
   `histogram_quantile(0.95, ...)` 算 p95/p99。

### 仅本地调试（无 collector）
设 `OTEL_ENABLED=True` 且 `OTEL_CONSOLE_EXPORT=True`，span/metrics 直接打到控制台。

## 降级与不变量

- **总开关优先**：`OTEL_ENABLED=False` → 一行不执行，无任何 OTel 开销（保证测试与现有行为不变）。
- **不阻断启动**：SDK 依赖缺失、OTLP exporter 缺失、单项埋点失败，均只记 `error`/`warning` 日志后继续。
- **未配 endpoint 不报错**：自动降级控制台导出并 `warning` 提示。
- **关闭要 flush**：进程退出前 `shutdown_telemetry()` 刷出 BatchSpanProcessor 缓冲，避免丢尾部 span。

## 测试

OTel 默认关闭，单测不依赖它。验证方式：
- 关闭路径：`python -m pytest`（测试不受影响即证明 no-op）。
- 启用路径冒烟：设 `OTEL_ENABLED=true OTEL_CONSOLE_EXPORT=true` 导入 `app.main`，确认
  provider 已设置、`app._is_instrumented_by_opentelemetry` 为 True、`/readyz` 与 `/metrics/json` 在路由表。

## 扩展指引

- **加埋点目标**（如 httpx 外呼）：装对应 `opentelemetry-instrumentation-*` 包，在 `_instrument_all`
  里加一段 try/except 调用其 instrumentor。
- **自定义业务 span**：`from opentelemetry import trace; tracer = trace.get_tracer(__name__)`，
  用 `with tracer.start_as_current_span("name"):` 包裹关键业务逻辑。
- **多 worker 注意**：每个 worker 进程各自装配 provider（OTLP 推送模型下无需共享状态，天然支持）。
