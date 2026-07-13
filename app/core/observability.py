"""OpenTelemetry 可观测性接入（traces + metrics，OTLP 导出）。

设计原则（与项目"可降级"哲学一致）：
- **默认关闭**：`OTEL_ENABLED=False` 时 `setup_telemetry` 立即返回，零运行时开销，
  现有行为与测试完全不受影响。
- **依赖软引入**：所有 OTel 包在函数内 import；即使未安装也只记日志、不崩溃。
- **导出器降级**：配了 `OTEL_EXPORTER_OTLP_ENDPOINT` 走 OTLP；否则降级为控制台导出
  （仅适合本地调试），绝不阻断启动。
- **埋点逐项容错**：FastAPI / SQLAlchemy / Redis 自动埋点各自 try/except，
  单项失败不影响其余。

埋点范围：
- FastAPI：HTTP server span + `http.server.*` 指标（含延迟直方图 → p95/p99）。
- SQLAlchemy：DB 查询 span（经 async engine 的 sync_engine 接入）。
- Redis：缓存/限流的 Redis 调用 span。
  （不额外接 asyncpg，避免与 SQLAlchemy span 重复嵌套。）
"""

from typing import Any, Optional

from app import __version__
from app.core.config import settings
from app.core.loguru_logger import get_logger

logger = get_logger("observability")

# 持有 providers 以便关闭时 flush（见 shutdown_telemetry）。
_tracer_provider: Optional[Any] = None
_meter_provider: Optional[Any] = None


def setup_telemetry(app, engine) -> None:
    """装配 OpenTelemetry。在 main.py 创建 app 后调用一次。

    Args:
        app: FastAPI 应用实例（用于 FastAPI 自动埋点）。
        engine: SQLAlchemy async engine（用于 DB 埋点，内部取 sync_engine）。
    """
    global _tracer_provider, _meter_provider

    if not settings.OTEL_ENABLED:
        logger.info("可观测性(OTel): 已禁用 (OTEL_ENABLED=False)")
        return

    # 应用工厂可能构造多个 FastAPI 实例。全局 provider / DB / Redis 只装配一次，
    # 后续实例只补 FastAPI app 级埋点，避免重复 provider 和重复 instrument 警告。
    if _tracer_provider is not None and _meter_provider is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
        except Exception as exc:  # noqa: BLE001
            logger.warning("可观测性(OTel): FastAPI 埋点失败", error=str(exc))
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:
        logger.error(
            "可观测性(OTel): SDK 依赖缺失，已跳过装配。"
            "请安装 requirements.txt 中的 opentelemetry-* 包",
            error=str(exc),
        )
        return

    resource = Resource.create(
        {"service.name": settings.OTEL_SERVICE_NAME, "service.version": __version__}
    )

    span_exporter, metric_exporter, sink = _build_exporters()
    if span_exporter is None or metric_exporter is None:
        # 构建导出器失败（如缺对应 exporter 包），已在 _build_exporters 记日志，放弃装配。
        return

    # ---- Traces ----
    sampler = ParentBased(TraceIdRatioBased(settings.OTEL_TRACES_SAMPLER_RATIO))
    _tracer_provider = TracerProvider(resource=resource, sampler=sampler)
    _tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(_tracer_provider)

    # ---- Metrics ----
    reader = PeriodicExportingMetricReader(metric_exporter)
    _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(_meter_provider)

    # ---- 自动埋点 ----
    _instrument_all(app, engine)

    logger.info(
        "可观测性(OTel): 已启用",
        sink=sink,
        service=settings.OTEL_SERVICE_NAME,
        sampler_ratio=settings.OTEL_TRACES_SAMPLER_RATIO,
    )


def _build_exporters():
    """按配置构建 span/metric 导出器。

    返回 (span_exporter, metric_exporter, sink_label)；构建失败返回 (None, None, "")。
    优先级：OTEL_CONSOLE_EXPORT 或未配 endpoint → 控制台；否则 → OTLP(grpc/http)。
    """
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT

    if settings.OTEL_CONSOLE_EXPORT or not endpoint:
        if not endpoint and not settings.OTEL_CONSOLE_EXPORT:
            logger.warning(
                "可观测性(OTel): 未配置 OTEL_EXPORTER_OTLP_ENDPOINT，"
                "降级为控制台导出（仅适合本地调试）"
            )
        return ConsoleSpanExporter(), ConsoleMetricExporter(), "console"

    protocol = (settings.OTEL_EXPORTER_OTLP_PROTOCOL or "grpc").lower()
    try:
        if protocol.startswith("http"):
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter as HttpMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter as HttpSpanExporter,
            )

            span_exporter_factory: Any = HttpSpanExporter
            metric_exporter_factory: Any = HttpMetricExporter
        else:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter as GrpcMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as GrpcSpanExporter,
            )

            span_exporter_factory = GrpcSpanExporter
            metric_exporter_factory = GrpcMetricExporter
    except ImportError as exc:
        logger.error(
            "可观测性(OTel): OTLP exporter 依赖缺失，已跳过装配",
            protocol=protocol,
            error=str(exc),
        )
        return None, None, ""

    return (
        span_exporter_factory(endpoint=endpoint),
        metric_exporter_factory(endpoint=endpoint),
        f"otlp/{protocol} -> {endpoint}",
    )


def _instrument_all(app, engine) -> None:
    """对 FastAPI / SQLAlchemy / Redis 自动埋点，逐项容错。"""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # noqa: BLE001 - 埋点失败不应影响应用启动
        logger.warning("可观测性(OTel): FastAPI 埋点失败", error=str(exc))

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        # async engine 需传其底层 sync_engine
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    except Exception as exc:  # noqa: BLE001
        logger.warning("可观测性(OTel): SQLAlchemy 埋点失败", error=str(exc))

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        logger.warning("可观测性(OTel): Redis 埋点失败", error=str(exc))


def shutdown_telemetry() -> None:
    """关闭时 flush 并释放 providers（在 lifespan 关闭段调用）。"""
    global _tracer_provider, _meter_provider
    for provider, label in ((_tracer_provider, "tracer"), (_meter_provider, "meter")):
        if provider is not None:
            try:
                provider.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"可观测性(OTel): {label} provider 关闭异常", error=str(exc)
                )
    _tracer_provider = None
    _meter_provider = None


# ---------------------------------------------------------------------------
# 关闭任务：OTel providers 释放
# ---------------------------------------------------------------------------
# 原在 main.py lifespan 关闭段直接调用 shutdown_telemetry()，现收敛到本模块并以
# @register_shutdown 自注册。priority=10 先于 Redis（priority=20）关闭——OTel 先 flush，
# 避免后续关闭动作的 span 丢失。OTel 关闭是同步调用，包一层 async 适配注册表签名。

from app.core.lifecycle import register_shutdown  # noqa: E402


@register_shutdown("telemetry", priority=10)
async def shutdown_telemetry_task() -> None:
    """关闭任务：flush 并释放 OTel providers（未启用时 no-op）。"""
    shutdown_telemetry()
