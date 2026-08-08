import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.core.config import settings
from app.core.lifecycle import (
    register_startup,
    run_shutdown,
    run_startup,
)
from app.core.loguru_logger import flush_logs, get_logger, init_logging
from app.core.app_runtime import process_runtime_guard
from app.middleware.monitoring import (
    SecurityHeadersMiddleware,
    MetricsMiddleware,
    LoggingMiddleware,
)
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, AuthRateLimitMiddleware
from app.middleware.api_usage import ApiUsageMiddleware
from app.core.exceptions import setup_exception_handlers, ExceptionHandlerMiddleware
from app.core.observability import setup_telemetry
from app.middleware.rbac import require_permission
from app.models.user import User

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
    if not settings.api_docs_enabled:
        logger.info("API 文档已关闭 (ENABLE_API_DOCS=False / DEBUG=False)")
    host = os.environ.get("APP_HOST")
    port = os.environ.get("APP_PORT")
    if host and port:
        # 0.0.0.0 / :: 是通配绑定地址，浏览器无法直接访问，展示为 localhost 方便本地点击
        display_host = "localhost" if host in ("0.0.0.0", "::") else host
        base_url = f"http://{display_host}:{port}"
        logger.info(f"应用访问地址: {base_url}")
        if settings.api_docs_enabled:
            logger.info(f"API 文档（Swagger）: {base_url}{settings.API_V1_STR}/docs")
            logger.info(f"OpenAPI: {base_url}{settings.API_V1_STR}/openapi.json")
    elif settings.api_docs_enabled:
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
    process_runtime_guard.acquire(app)

    try:
        # —— 应用级一次性展示（非任务，不进注册表）——
        logger.info(
            "\n"
            + _STARTUP_BANNER.format(
                name=settings.PROJECT_NAME,
                version=__version__,
            )
        )
        logger.info("FastAPI RBAC Framework 启动中...")
        if not settings.AUTH_ENABLED:
            logger.warning(
                "⚠️ 鉴权已全局关闭 (AUTH_ENABLED=False)——所有接口视为超级用户，"
                "仅限本地开发，切勿用于生产"
            )

        # —— 启动任务：遍历注册表执行（critical 失败会 raise → 中止启动）——
        await run_startup()

        logger.info(f"FastAPI RBAC Framework 已启动成功 - version: {__version__}")

        try:
            yield
        finally:
            # —— 关闭任务：即使 lifespan 被取消/抛错，也必须释放后台任务与连接 ——
            await run_shutdown()
            logger.info(f"应用已安全关闭 - version: {__version__}")
            # 排空异步日志队列（LOG_ENQUEUE=True 时日志由后台线程落盘）。
            # 必须放在最后一条日志之后：否则关闭阶段的日志会随进程退出一起丢掉。
            await flush_logs()
    finally:
        process_runtime_guard.release(app)


root_router = APIRouter()


def create_app() -> FastAPI:
    """构造独立 FastAPI 实例，同时保留模块级 ``app`` 部署入口。"""
    # 文档默认跟随 DEBUG：生产环境不把完整 API 结构暴露给未认证用户。
    # 传 None 给 FastAPI 即彻底不注册这些路由（不是返回 404 的假关闭）。
    docs_on = settings.api_docs_enabled
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="企业级FastAPI框架，包含RBAC权限管理系统",
        version=__version__,
        openapi_url=f"{settings.API_V1_STR}/openapi.json" if docs_on else None,
        lifespan=lifespan,
        docs_url=f"{settings.API_V1_STR}/docs" if docs_on else None,
        redoc_url=f"{settings.API_V1_STR}/redoc" if docs_on else None,
    )
    setup_exception_handlers(application)

    # Starlette 后注册的中间件在更外层，故按内 → 外添加。
    # 体积闸门放最内层：限流先于它执行（超频请求根本不该走到读 body 这步）。
    application.add_middleware(
        BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES
    )
    application.add_middleware(
        AuthRateLimitMiddleware,
        calls=settings.AUTH_RATE_LIMIT_CALLS,
        period=settings.AUTH_RATE_LIMIT_PERIOD,
    )
    application.add_middleware(
        RateLimitMiddleware,
        calls=settings.RATE_LIMIT_CALLS,
        period=settings.RATE_LIMIT_PERIOD,
    )
    application.add_middleware(MetricsMiddleware)
    application.add_middleware(LoggingMiddleware)
    application.add_middleware(ApiUsageMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(ExceptionHandlerMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=settings.allowed_methods_list,
        allow_headers=settings.allowed_headers_list,
    )

    from app.database import engine

    setup_telemetry(application, engine)
    application.include_router(api_router, prefix=settings.API_V1_STR)
    application.include_router(root_router)

    # 事件订阅注册（幂等；业务事件 → 站内通知等副作用）
    from app.services.notification_events import register_notification_events

    register_notification_events()
    return application


# 根路径
@root_router.get("/")
async def root():
    payload = {"message": "欢迎使用企业级FastAPI RBAC框架"}
    if settings.api_docs_enabled:
        payload["docs_url"] = f"{settings.API_V1_STR}/docs"
        payload["redoc_url"] = f"{settings.API_V1_STR}/redoc"
    return payload


# 健康检查端点（liveness：进程是否存活，浅检查，供 k8s livenessProbe）
@root_router.get("/health")
async def health_check():
    return {"status": "healthy"}


# 事件总线健康检查：返回各事件监听器数量
@root_router.get("/health/events")
async def health_events():
    """返回事件总线上各事件注册的监听器数量（规划中 → 已实现）。
    无需鉴权：供运维 / 探针快速定位事件处理链路是否正常。
    """
    from app.core.events import event_bus

    subscribers = {}
    for event, handlers in event_bus._subscribers.items():
        subscribers[event] = len(handlers)
    return {"status": "healthy", "subscribers": subscribers}


# 安全健康检查：返回限流器/会话/迁移状态
@root_router.get("/health/security")
async def health_security():
    """返回安全相关组件健康状态（规划中 → 已实现）。
    无需鉴权：供运维探针快速定位安全组件异常。
    """
    from app.core.rate_limit import get_limiter
    from app.core.config import settings
    from app.utils.status import check_database_connection, check_redis_connection

    limiter = get_limiter()
    # 限流器后端是否 Redis（跨实例一致）
    rate_limit_redis = limiter.using_redis

    # 会话黑名单状态
    from app.core.security_blacklist import get_blacklist

    blacklist = get_blacklist()
    blacklist_type = type(blacklist).__name__

    # 检查数据库迁移状态
    db_status = await check_database_connection()
    redis_status = await check_redis_connection()

    return {
        "status": "healthy",
        "rate_limiter": {
            "using_redis": rate_limit_redis,
            "redis_configured": bool(settings.REDIS_URL),
        },
        "token_blacklist": {
            "backend": blacklist_type,
            "redis_configured": bool(settings.REDIS_URL),
        },
        "auth": {
            "enabled": settings.AUTH_ENABLED,
            "totp_encryption_key_set": bool(settings.TOTP_ENCRYPTION_KEY),
        },
        "migration": {
            "database": db_status.get("status", "unknown"),
            "redis": redis_status.get("status", "unknown"),
        },
        "multi_instance": {
            "enabled": os.getenv("MULTI_INSTANCE", "false").strip().lower()
            in ("1", "true", "yes", "on"),
            "workers": settings.WORKERS,
        },
    }


# 就绪探针（readiness：依赖是否就绪，供 k8s readinessProbe）
# DB 不通时返回 503，避免把流量打到尚未就绪/依赖故障的实例。
@root_router.get("/readyz")
async def readiness_check():
    """就绪判定只探 DB（Redis 可降级，不影响就绪）。

    这里刻意不复用 ``check_application_status``：那个函数还会跑 ``SELECT version()``
    和 Redis ping，而就绪只需要一个布尔值——探针频率高，多余的往返要省掉。
    """
    from fastapi.responses import JSONResponse
    from app.utils.status import ping_database

    if await ping_database():
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not_ready"})


# 指标端点（人读 JSON 版；OTel 启用后标准指标经 OTLP 导出至 collector）
@root_router.get("/metrics/json")
async def metrics_json(
    request: Request,
    current_user: User = Depends(require_permission("system", "monitor")),
):
    """获取应用性能指标（手搓内存版，便于 curl 速览）。

    注：分布式监控请用 OpenTelemetry（OTEL_ENABLED=True，指标经 OTLP 导出，
    含延迟直方图/分位数）；本端点仅为单实例快速排查保留。
    """
    instance = getattr(request.app.state, "metrics_middleware", None)
    if instance is None:
        return {"error": "Metrics not available"}
    return instance.get_metrics()


# 状态端点
@root_router.get("/status")
async def status(
    current_user: User = Depends(require_permission("system", "monitor")),
):
    """获取应用详细状态"""
    from app.utils.status import check_application_status

    return await check_application_status()


# ASGI 部署兼容入口：uvicorn 继续使用 ``app.main:app``。
app = create_app()
