import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.core.config import settings
from app.core.loguru_logger import get_logger, init_logging
from app.database import engine
from app.models import Base
from app.middleware.monitoring import SecurityHeadersMiddleware, MetricsMiddleware, LoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, AuthRateLimitMiddleware
from app.core.exceptions import setup_exception_handlers, ExceptionHandlerMiddleware
from app.core.observability import setup_telemetry, shutdown_telemetry


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


async def _verify_alembic_version(logger) -> None:
    """校验数据库迁移版本与代码 head 一致；不一致则 fail fast 拒绝启动。

    统一用 alembic 管理 schema 后，应用启动只“检查”不“自动迁移”——既避免多实例并发
    自动 upgrade 的竞态，又把“忘了跑迁移”从一堆 relation does not exist 变成一句清晰提示。
    真正的迁移由独立步骤执行：alembic upgrade head。
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    def _read_revisions(sync_conn):
        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        script = ScriptDirectory.from_config(Config(str(ini_path)))
        head = script.get_current_head()
        current = MigrationContext.configure(sync_conn).get_current_revision()
        return head, current

    async with engine.connect() as conn:
        head, current = await conn.run_sync(_read_revisions)

    if current == head:
        logger.info("数据库迁移版本已是最新", revision=current)
        return

    logger.error(
        "数据库迁移版本不一致，拒绝启动",
        current=current or "(未迁移/无 alembic_version)",
        expected=head,
    )
    raise RuntimeError(
        f"数据库迁移版本不一致：当前={current or '(未迁移/无 alembic_version)'}，"
        f"代码最新={head}。请先执行 `alembic upgrade head` 再启动应用。"
    )


async def _run_alembic_upgrade(logger) -> None:
    """执行 alembic upgrade head（建表/升级到最新）。

    多 worker 并发安全由调用方的 advisory lock 保证（见 _serialized_startup_init 把
    建库/迁移/seed 整体串行化），本函数只负责执行 upgrade。
    """
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    def _upgrade():
        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        command.upgrade(Config(str(ini_path)), "head")

    # alembic command 是同步阻塞调用，放线程池避免阻塞事件循环
    await asyncio.to_thread(_upgrade)
    logger.info("已自动执行 alembic upgrade head (DB_AUTO_MIGRATE=True)")


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

    # 统一 alembic 管理 schema（DB_AUTO_CREATE=False）：
    #   DB_AUTO_MIGRATE=True  → 启动自动 upgrade head（建表/升级到最新，适合单实例/开发）
    #   DB_AUTO_MIGRATE=False → 仅校验版本一致性，不一致 fail fast（适合多实例生产）
    if not settings.DB_AUTO_CREATE:
        if settings.DB_AUTO_MIGRATE:
            await _run_alembic_upgrade(logger)
        else:
            await _verify_alembic_version(logger)


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


async def _serialized_startup_init(logger) -> None:
    """用 PostgreSQL advisory lock 串行化一次性启动初始化（建库 / 迁移 / seed）。

    多 worker 场景下 4 个进程同时启动，会并发跑 seed 导致重复 INSERT 撞唯一约束
    （如 admin email）。这里用集群级全局锁保证同一时刻只有一个进程执行：抢到锁的真正
    初始化，其余阻塞等待；待其完成释放锁后，迁移已 no-op、seed 检查到已存在直接跳过（幂等）。
    锁连接用维护库（一定存在）——因为目标库此刻可能还没建。
    """
    import asyncpg
    from sqlalchemy.engine import make_url

    _STARTUP_LOCK_KEY = 873924001
    url = make_url(settings.DATABASE_URL)
    lock_conn = await asyncpg.connect(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=settings.DB_MAINTENANCE_DB,
    )
    try:
        # advisory lock 是集群级（跨库跨 session），维护库上持锁即可保护目标库的初始化
        await lock_conn.execute("SELECT pg_advisory_lock($1)", _STARTUP_LOCK_KEY)
        await _initialize_database(logger)
        try:
            await _initialize_rbac(logger)
        except Exception as e:
            logger.error(f"RBAC系统初始化异常: {str(e)}")
    finally:
        await lock_conn.execute("SELECT pg_advisory_unlock($1)", _STARTUP_LOCK_KEY)
        await lock_conn.close()


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
    """输出应用启动状态。

    host/port 来自 run.py 写入的 APP_HOST/APP_PORT 环境变量（单一事实源 = uvicorn 实际绑定参数）。
    若环境变量缺失（如直接用 `uvicorn app.main:app` 启动而非 run.py），回退为只记相对路径，
    避免硬编码 host:port 与真实绑定不一致。
    """
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
    # 日志已在模块导入早期 init_logging 完成（见上），这里只做业务初始化
    logger = get_logger("main")

    # 应用启动
    logger.info("\n" + _STARTUP_BANNER.format(name=settings.PROJECT_NAME, version=__version__))
    logger.info("FastAPI RBAC Framework 启动中...")
    if not settings.AUTH_ENABLED:
        logger.warning(
            "⚠️ 鉴权已全局关闭 (AUTH_ENABLED=False)——所有接口视为超级用户，仅限本地开发，切勿用于生产"
        )
    # 建库 / 迁移 / seed 用 advisory lock 整体串行化：多 worker 下只有一个进程真正执行，
    # 其余等待后迁移 no-op、seed 幂等跳过，避免并发 seed 撞唯一约束。
    await _serialized_startup_init(logger)

    await _initialize_redis(logger)

    await _log_startup_status(logger)
    logger.info(f"FastAPI RBAC Framework 已启动成功 - version: {__version__}")

    yield

    # 应用关闭
    from app.core.redis_client import close_redis_client

    await close_redis_client()
    shutdown_telemetry()  # flush 并释放 OTel providers（未启用时 no-op）
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
