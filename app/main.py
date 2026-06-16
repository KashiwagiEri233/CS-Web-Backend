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
    """初始化数据库连接并创建表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
                logger.info(
                    "默认管理员账号已创建",
                    username="admin",
                    password="admin123",
                    note="请在生产环境中修改默认密码",
                )
        else:
            logger.error("RBAC系统初始化失败", errors=init_result["errors"])


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
    await _initialize_database(logger)

    try:
        await _initialize_rbac(logger)
    except Exception as e:
        logger.error(f"RBAC系统初始化异常: {str(e)}")

    await _log_startup_status(logger)
    logger.info("FastAPI RBAC Framework 已启动成功 - version: 1.0.0")

    yield

    # 应用关闭
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

# 配置中间件（注意异常处理中间件应该放在最外层）
app.add_middleware(ExceptionHandlerMiddleware)
# 添加速率限制中间件
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
