import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.core.config import settings
from app.core.lifecycle import (
    register_startup,
    run_shutdown,
    run_startup,
)
from app.core.loguru_logger import get_logger, init_logging
from app.middleware.monitoring import SecurityHeadersMiddleware, MetricsMiddleware, LoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, AuthRateLimitMiddleware
from app.core.exceptions import setup_exception_handlers, ExceptionHandlerMiddleware
from app.core.observability import setup_telemetry


# 在产生任何应用日志前，于模块导入早期统一初始化日志。
# 关键：uvicorn reload 子进程只 import 本模块、不执行 run.py，若不在此初始化，
# import 阶段的日志（如 setup_telemetry 的 OTel 提示）会落到 loguru 默认 sink（写 stderr，
# 终端常显示为红色），与后续自定义格式（stdout，白色）不一致。幂等：内部先 remove 再 add。
init_logging(settings)


# 启动横幅（witchcat）。{name}/{version} 在 lifespan 里填充。
_STARTUP_BANNER = r"""
           |\      _,,,---,,_            .  *  .
     ZZzz /,`.-'`'    -.  ;-;;,_
          |,4-  ) )-,_. ,\ (  `'-'      WitchCat
         '---''(_/--'  `-'\_)           {name}
                                        v{version}  |  starting up...
"""


@register_startup("log_status", priority=90, critical=False)
async def startup_log_status() -> None:
    """启动任务：输出应用启动状态（访问地址 / 文档路径）。

    priority=90 置于所有初始化任务之后，确保展示的信息反映「已成功就绪」的状态。
    host/port 来自 run.py 写入的 APP_HOST/APP_PORT 环境变量（单一事实源 = uvicorn
    实际绑定参数）；缺失（如直接用 ``uvicorn app.main:app``）时回退为只记相对路径，
    避免硬编码 host:port 与真实绑定不一致。
    """
    logger = get_logger("main")
    host = os.environ.get("APP_HOST")
    port = os.environ.get("APP_PORT")
    if host and port:
        # 0.0.0.0 / :: 是通配绑定地址，浏览器无法直接访问，展示为 localhost 方便本地点击
        display_host = "localhost" if host in ("0.0.0.0", "::") else host
        base_url = f"http://{display_host}:{port}"
        logger.info(f"应用访问地址: {base_url}")
        logger.info(f"API 文档（Swagger）: {base_url}{settings.API_V1_STR}/docs")
        logger.info(f"OpenAPI: {base_url}{settings.API_V1_STR}/openapi.json")
    else:
        logger.info(f"API 文档路径: {settings.API_V1_STR}/docs")
        logger.info(f"OpenAPI: {settings.API_V1_STR}/openapi.json")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动横幅 + 注册表驱动的启动 / 关闭任务。

    DB / RBAC seed / Redis 探测等具体初始化逻辑已迁移到各自模块并以
    ``@register_startup`` 自注册（见 ``app/core/lifecycle/``），这里只负责遍历执行。
    横幅与 AUTH_ENABLED 告警属于应用级一次性展示（非幂等、无 priority 概念），
    不进注册表，在此直接输出。
    """
    logger = get_logger("main")

    # —— 应用级一次性展示（非任务，不进注册表）——
    logger.info("\n" + _STARTUP_BANNER.format(name=settings.PROJECT_NAME, version=__version__))
    logger.info("FastAPI RBAC Framework 启动中...")
    if not settings.AUTH_ENABLED:
        logger.warning(
            "⚠️ 鉴权已全局关闭 (AUTH_ENABLED=False)——所有接口视为超级用户，仅限本地开发，切勿用于生产"
        )

    # —— 启动任务：遍历注册表执行（critical 失败会 raise → 中止启动）——
    await run_startup()

    logger.info(f"FastAPI RBAC Framework 已启动成功 - version: {__version__}")

    yield

    # —— 关闭任务：遍历注册表执行（按 priority 降序，异常一律吞掉只记日志）——
    await run_shutdown()
    logger.info(f"应用已安全关闭 - version: {__version__}")


# 创建FastAPI应用实例
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="企业级FastAPI框架，包含RBAC权限管理系统",
    version=__version__,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

# 设置全局异常处理器
setup_exception_handlers(app)

# 配置中间件
# 重要：Starlette 中 add_middleware 后注册的在更外层。
# 期望的执行顺序（外 -> 内）：
#   CORS -> 异常处理 -> 安全头 -> 日志 -> 指标 -> 限流 -> 认证限流 -> 路由
# 因此注册顺序需自内向外。异常处理放在 CORS 之内、其余功能中间件之外，
# 这样它能捕获任何功能中间件抛出的异常并映射为正确状态码，而错误响应仍会被 CORS 装饰。
app.add_middleware(
    AuthRateLimitMiddleware,
    calls=settings.AUTH_RATE_LIMIT_CALLS,
    period=settings.AUTH_RATE_LIMIT_PERIOD,
)
app.add_middleware(
    RateLimitMiddleware,
    calls=settings.RATE_LIMIT_CALLS,
    period=settings.RATE_LIMIT_PERIOD,
)
app.add_middleware(MetricsMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# 异常处理中间件：包裹上述所有功能中间件（但在 CORS 之内）
app.add_middleware(ExceptionHandlerMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=settings.allowed_methods_list,
    allow_headers=settings.allowed_headers_list,
)

# 可观测性（OpenTelemetry）：在中间件装配完成后接入。
# OTEL_ENABLED=False 时为 no-op；自动埋点 FastAPI / SQLAlchemy / Redis。
# 注：engine 导入放在装配处而非模块顶，避免与 lifecycle 注册解耦后无关的全局开销。
from app.database import engine  # noqa: E402

setup_telemetry(app, engine)

# 注册API路由
app.include_router(api_router, prefix=settings.API_V1_STR)


# 根路径
@app.get("/")
async def root():
    return {
        "message": "欢迎使用企业级FastAPI RBAC框架",
        "docs_url": f"{settings.API_V1_STR}/docs",
        "redoc_url": f"{settings.API_V1_STR}/redoc",
    }


# 健康检查端点（liveness：进程是否存活，浅检查，供 k8s livenessProbe）
@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# 就绪探针（readiness：依赖是否就绪，供 k8s readinessProbe）
# DB 不通时返回 503，避免把流量打到尚未就绪/依赖故障的实例。
@app.get("/readyz")
async def readiness_check():
    from fastapi.responses import JSONResponse
    from app.utils.status import check_application_status

    status_info = await check_application_status()
    db_ok = status_info.get("database", {}).get("status") == "connected"
    if db_ok:
        return {"status": "ready", **status_info}
    return JSONResponse(status_code=503, content={"status": "not_ready", **status_info})


# 指标端点（人读 JSON 版；OTel 启用后标准指标经 OTLP 导出至 collector）
@app.get("/metrics/json")
async def metrics_json():
    """获取应用性能指标（手搓内存版，便于 curl 速览）。

    注：分布式监控请用 OpenTelemetry（OTEL_ENABLED=True，指标经 OTLP 导出，
    含延迟直方图/分位数）；本端点仅为单实例快速排查保留。
    """
    instance = MetricsMiddleware._instance
    if instance is None:
        return {"error": "Metrics not available"}
    return instance.get_metrics()


# 状态端点
@app.get("/status")
async def status():
    """获取应用详细状态"""
    from app.utils.status import check_application_status

    return await check_application_status()
