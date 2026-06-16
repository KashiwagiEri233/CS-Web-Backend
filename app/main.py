import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.loguru_logger import get_logger
from app.database import engine
from app.models import Base
from app.middleware.monitoring import SecurityHeadersMiddleware, MetricsMiddleware, LoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, AuthRateLimitMiddleware
from app.core.exceptions import setup_exception_handlers, ExceptionHandlerMiddleware


async def _initialize_database(logger):
    """初始化数据库（按配置：先确保库存在，再决定是否自动建表）"""
    if settings.DB_AUTO_CREATE_DATABASE:
        from app.database import ensure_database_exists

        created = await ensure_database_exists()
        logger.info("目标数据库已自动创建" if created else "目标数据库已存在")

    if settings.DB_AUTO_CREATE:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("已自动建表 (DB_AUTO_CREATE=True)")
    else:
        logger.info("跳过自动建表 (DB_AUTO_CREATE=False)，请确保已执行 alembic upgrade head")

    from app.utils.status import check_database_connection

    db_status = await check_database_connection()

    if db_status["status"] == "connected":
        logger.info(
            "数据库连接成功", type=db_status["type"], version=db_status["version"]
        )
    else:
        msg = db_status.get("message", "Unknown error")
        logger.error("数据库连接失败", message=msg)
        raise Exception(f"Database connection failed: {msg}")


async def _initialize_rbac(logger):
    """初始化 RBAC 权限系统"""
    from app.database import AsyncSessionLocal
    from app.services.rbac_init import initialize_rbac

    async with AsyncSessionLocal() as db:
        init_result = await initialize_rbac(db)
        if init_result["success"]:
            logger.info(
                "RBAC系统初始化成功",
                permissions_created=init_result["permissions_created"],
                roles_created=init_result["roles_created"],
                admin_created=init_result["admin_created"],
            )
            if init_result["admin_created"]:
                if init_result.get("admin_password_generated"):
                    logger.warning(
                        "默认管理员已创建，初始密码为随机生成，请立即登录并修改（仅显示这一次）",
                        username=settings.ADMIN_USERNAME,
                        password=init_result["generated_admin_password"],
                    )
                else:
                    logger.info(
                        "默认管理员已创建（密码来自 ADMIN_PASSWORD 配置，未写入日志）",
                        username=settings.ADMIN_USERNAME,
                    )
        else:
            logger.error("RBAC系统初始化失败", errors=init_result["errors"])


async def _initialize_redis(logger):
    """探测 Redis（可选）。未配置或不可用都不阻断启动——限流会自动降级。"""
    if not settings.REDIS_URL:
        logger.info("限流后端: 内存模式（未配置 REDIS_URL）")
        return

    from app.core.redis_client import ping_redis

    if await ping_redis():
        logger.info("限流后端: Redis（已连通）", fallback=settings.RATE_LIMIT_FALLBACK)
    else:
        logger.warning(
            "已配置 REDIS_URL 但当前不可用，启动后将按 fallback 策略降级运行",
            fallback=settings.RATE_LIMIT_FALLBACK,
        )


async def _log_startup_status(logger):
    """输出应用启动状态"""
    logger.info("服务器地址: http://0.0.0.0:8000")
    logger.info(f"API文档: http://0.0.0.0:8000{settings.API_V1_STR}/docs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 日志已在模块加载时配置完成，这里只做业务初始化
    logger = get_logger("main")

    # 应用启动
    logger.info("FastAPI RBAC Framework 启动中...")
    if not settings.AUTH_ENABLED:
        logger.warning(
            "⚠️ 鉴权已全局关闭 (AUTH_ENABLED=False)——所有接口视为超级用户，仅限本地开发，切勿用于生产"
        )
    await _initialize_database(logger)

    try:
        await _initialize_rbac(logger)
    except Exception as e:
        logger.error(f"RBAC系统初始化异常: {str(e)}")

    await _initialize_redis(logger)

    await _log_startup_status(logger)
    logger.info("FastAPI RBAC Framework 已启动成功 - version: 1.0.0")

    yield

    # 应用关闭
    from app.core.redis_client import close_redis_client

    await close_redis_client()
    logger.info("应用已安全关闭 - version: 1.0.0")


# 创建FastAPI应用实例
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="企业级FastAPI框架，包含RBAC权限管理系统",
    version="1.0.0",
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
    allow_origins=settings.ALLOWED_ORIGINS,  # 从配置文件读取允许的源
    allow_credentials=True,
    allow_methods=settings.ALLOWED_METHODS,  # 从配置文件读取允许的方法
    allow_headers=settings.ALLOWED_HEADERS,  # 从配置文件读取允许的头部
)

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


# 健康检查端点
@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# 监控端点
@app.get("/metrics")
async def metrics():
    """获取应用性能指标"""
    # 获取中间件实例
    for middleware in app.user_middleware:
        if (
            hasattr(middleware.cls, "__name__")
            and "MetricsMiddleware" in middleware.cls.__name__
        ):
            metrics_instance = middleware.instance
            if hasattr(metrics_instance, "get_metrics"):
                return metrics_instance.get_metrics()

    return {"error": "Metrics not available"}


# 状态端点
@app.get("/status")
async def status():
    """获取应用详细状态"""
    from app.utils.status import check_application_status

    return await check_application_status()
