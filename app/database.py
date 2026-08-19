from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from pathlib import Path

from app.core.config import settings
from app.core.constants import CONNECTION_POOL_BUDGET_RATIO


# SQLAlchemy 2.0 风格的基类
class Base(DeclarativeBase):
    pass


# 创建异步数据库引擎
# 连接池参数由 Settings 驱动（见 config.py DB_POOL_*）：生产下 pool_pre_ping 防陈旧连接，
# pool_recycle 主动回收长连接，pool_size/max_overflow 控制并发上限。
_engine_options: Dict[str, Any] = {
    "echo": False,
    "future": True,
    "pool_size": settings.DB_POOL_SIZE,
    "max_overflow": settings.DB_MAX_OVERFLOW,
    "pool_timeout": settings.DB_POOL_TIMEOUT,
    "pool_recycle": settings.DB_POOL_RECYCLE,
    "pool_pre_ping": settings.DB_POOL_PRE_PING,
}
if settings.TESTING:
    # pytest-asyncio 默认可能为每个测试创建事件循环；asyncpg 连接绑定创建它的
    # loop，跨测试复用池连接会触发 “Future attached to a different loop”。
    _engine_options = {"echo": False, "future": True, "poolclass": NullPool}

engine = create_async_engine(settings.database_url, **_engine_options)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# alembic.ini 位于项目根（app/ 的上一级）；run_alembic_upgrade / _verify_alembic_version
# 两处共用此常量，避免路径散落重复（方案「database.py alembic.ini 路径常量化」）。
ALEMBIC_INI_PATH = Path(__file__).resolve().parent.parent / "alembic.ini"


async def ensure_database_exists() -> bool:
    """若目标数据库不存在则创建。

    Postgres 不会自动建库，这里连接到维护库（默认 postgres）检查并 CREATE DATABASE。
    返回 True 表示本次新建，False 表示已存在或未配置。
    """
    import re
    import asyncpg
    from sqlalchemy.engine import make_url

    url = make_url(settings.database_url)
    db_name = url.database
    if not db_name:
        return False
    # 库名来自配置而非用户输入，但 CREATE DATABASE 不能参数化，仍做标识符白名单校验
    if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
        raise ValueError(f"非法数据库名（仅允许字母数字下划线）: {db_name!r}")

    conn = await asyncpg.connect(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=settings.DB_MAINTENANCE_DB,
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if exists:
            return False
        try:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            return True
        except (
            asyncpg.exceptions.DuplicateDatabaseError,
            asyncpg.exceptions.UniqueViolationError,
        ):
            # 多 worker 并发抢先建库：DuplicateDatabase（检测到已存在）或 pg_database 唯一索引
            # 冲突 UniqueViolation（两进程几乎同时 CREATE）——都视为已存在（幂等，不报错）
            return False
    finally:
        await conn.close()


# 获取数据库会话的依赖注入函数（FastAPI 路由用）
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """请求级会话：出异常回滚，退出时关闭；与路由外的 ``get_session`` 语义一致。

    不自动提交——由 service 层显式 commit，保证跨多个仓储的业务在同一事务内完成。
    （``async with`` 退出时本就会 close，无需再写一层 ``finally: close()``。）
    """
    async with AsyncSessionLocal() as session:
        failed = False
        try:
            yield session
        except BaseException:
            failed = True
            raise
        finally:
            # 安全网：get_db 不自动 commit。请求正常结束但会话仍有未提交的写
            # （flush 后未 commit，session.new/dirty 在 commit 前不会清空），说明
            # 写路由忘了显式 commit——数据会被静默回滚且接口仍返回 200。
            # 开发期用 warning 立刻暴露这类"假成功"。
            if not failed and (session.new or session.dirty or session.deleted):
                _db_logger.warning(
                    "请求结束但会话存在未提交的写操作，已回滚："
                    "写路由必须显式 commit（或经 audit.record_atomic 原子提交）"
                )


# 在 FastAPI 依赖体系之外安全使用会话（worker / 脚本 / 后台任务 / 队列消费者）。
# 路由用 Depends(get_db)，非请求上下文用 `async with get_session() as db:`。
@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """提供一个受管理的会话。

    用法：
        async with get_session() as db:
            await SomeService(db).do_something()
            await db.commit()

    出异常自动回滚；与路由层保持一致——不自动提交，由调用方显式 commit。
    """
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# 启动任务：数据库初始化（建库 / schema / 迁移）
# ---------------------------------------------------------------------------
# 以下逻辑原散落在 main.py 的 _initialize_database / _run_alembic_upgrade /
# _verify_alembic_version / _serialized_startup_init，现统一收敛到本模块并以
# @register_startup 自注册到 lifecycle 注册表（main.py 的 lifespan 只负责调用
# run_startup()，不再持有任何 DB 初始化细节）。

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.lifecycle import register_shutdown, register_startup  # noqa: E402
from app.core.loguru_logger import get_logger  # noqa: E402

_db_logger = get_logger("database")

# 集群级 advisory lock 的固定 key（与原 main.py 保持一致，多 worker 串行化用）。
_STARTUP_LOCK_KEY = 873924001


async def run_alembic_upgrade() -> None:
    """执行 alembic upgrade head（建表 / 升级到最新）。

    多 worker 并发安全由调用方（``_init_schema_under_lock``）的 advisory lock 保证，
    本函数只负责执行 upgrade。

    公共入口：``app/utils/db_initializer.py`` 的 ``DatabaseInitializer.apply_migrations``
    复用本函数，避免 alembic 路径/配置在两处重复。
    """
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    def _upgrade():
        ini_path = ALEMBIC_INI_PATH
        command.upgrade(Config(str(ini_path)), "head")

    # alembic command 是同步阻塞调用，放线程池避免阻塞事件循环
    await asyncio.to_thread(_upgrade)
    _db_logger.info("已自动执行 alembic upgrade head (DB_AUTO_MIGRATE=True)")


# 向后兼容别名（历史私有名）
_run_alembic_upgrade = run_alembic_upgrade


async def _verify_alembic_version() -> None:
    """校验数据库迁移版本与代码 head 一致；不一致则 fail fast 拒绝启动。

    统一用 alembic 管理 schema 后，应用启动只“检查”不“自动迁移”——既避免多实例
    并发自动 upgrade 的竞态，又把“忘了跑迁移”从一堆 relation does not exist
    变成一句清晰提示。真正的迁移由独立步骤执行：alembic upgrade head。
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    def _read_revisions(sync_conn):
        ini_path = ALEMBIC_INI_PATH
        script = ScriptDirectory.from_config(Config(str(ini_path)))
        heads = script.get_heads()
        current = MigrationContext.configure(sync_conn).get_current_revision()
        return heads, current

    async with engine.connect() as conn:
        heads, current = await conn.run_sync(_read_revisions)

    # 当前版本须为主链 head 之一（含独立可选维护迁移分支，如旧表 DROP）。
    # 仅当当前版本落后于所有 head 时才拒绝启动，避免强制应用"待评审"的可选迁移。
    if current in heads:
        _db_logger.info("数据库迁移版本已是最新", revision=current)
        return

    _db_logger.error(
        "数据库迁移版本不一致，拒绝启动",
        current=current or "(未迁移/无 alembic_version)",
        expected_heads=heads,
    )
    raise RuntimeError(
        f"数据库迁移版本不一致：当前={current or '(未迁移/无 alembic_version)'}，"
        f"代码最新 heads={heads}。请先执行 `alembic upgrade head` 再启动应用。"
    )


async def _init_schema() -> None:
    """在目标库已存在的前提下，按 Alembic 完成 schema 初始化。

    **唯一建表路径 = Alembic**（不再支持 Base.metadata.create_all）。
    - DB_AUTO_MIGRATE=True  → 自动 ``alembic upgrade head``
    - DB_AUTO_MIGRATE=False → 仅校验版本一致性，不一致 fail fast

    历史字段 ``DB_AUTO_CREATE`` 已彻底移除（Settings 配置了 extra="ignore"，
    旧 .env 里残留该项不会导致启动失败）。
    """
    _db_logger.info("schema 由 Alembic 管理")
    if settings.DB_AUTO_MIGRATE:
        await _run_alembic_upgrade()
    else:
        await _verify_alembic_version()


async def _check_connection() -> None:
    """建表 / 迁移完成后做一次连通性 + 版本探测；不通则 raise（critical 任务语义）。"""
    from app.utils.status import check_database_connection

    db_status = await check_database_connection()
    if db_status["status"] == "connected":
        _db_logger.info(
            "数据库连接成功", type=db_status["type"], version=db_status["version"]
        )
    else:
        msg = db_status.get("message", "Unknown error")
        _db_logger.error("数据库连接失败", message=msg)
        raise RuntimeError(f"Database connection failed: {msg}")


async def _check_pool_capacity() -> None:
    """校验「worker 数 × 单进程连接池上限」是否超出 PostgreSQL 的 max_connections。

    每个 uvicorn worker 是独立进程、各自持有一套连接池，总连接需求是
    ``workers × (DB_POOL_SIZE + DB_MAX_OVERFLOW)``。默认值 4 × (10 + 20) = 120，
    已经超过 PostgreSQL 默认的 max_connections=100——压到峰值才会暴露，
    而且报错形式是「连不上库」，很难第一时间联想到配置。启动时先算一遍并告警。

    只告警不拒绝启动：真实上限还要扣掉 superuser 预留和其它服务的占用，
    这里没有足够信息做硬判定，误杀启动的代价高于漏报。
    """
    import os

    try:
        workers = max(int(os.environ.get("APP_WORKERS", "1")), 1)
    except ValueError:
        workers = 1

    per_worker = settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW
    required = workers * per_worker

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SHOW max_connections"))
            max_connections = int(result.scalar_one())
    except Exception:  # noqa: BLE001 - 容量校验是提示性的，探测失败不影响启动
        _db_logger.debug("无法读取 max_connections，跳过连接池容量校验")
        return

    # 留出余量：superuser 预留连接 + 迁移/运维工具的临时连接
    budget = int(max_connections * CONNECTION_POOL_BUDGET_RATIO)
    if required > budget:
        _db_logger.warning(
            "连接池总量可能超出数据库上限",
            workers=workers,
            per_worker=per_worker,
            required=required,
            max_connections=max_connections,
            hint=(
                "workers × (DB_POOL_SIZE + DB_MAX_OVERFLOW) 应留在 max_connections "
                "的 80% 以内；请调小连接池或 worker 数，或调高 PostgreSQL max_connections"
            ),
        )


async def _init_schema_under_lock() -> None:
    """用 PostgreSQL advisory lock 串行化 schema 初始化（建库 + 建表 / 迁移）。

    多 worker 场景下多个进程同时启动，会并发建库 / 建表撞冲突。用集群级全局锁保证
    同一时刻只有一个进程执行 schema 操作；其余阻塞等待，待其完成后迁移 no-op（幂等）。
    锁连接连到维护库（一定存在）——因为目标库此刻可能还没建。

    注：RBAC seed 由自身独立的 advisory lock 串行化，避免多 worker 查重后同时插入；
    与 schema 初始化（priority=10）保持解耦。
    """
    # 仅做版本校验时没有写 schema 的竞态，无需连接维护库或持 advisory lock。
    # 这也允许生产环境使用只能连接目标库的最小权限账号。
    if not settings.DB_AUTO_CREATE_DATABASE and not settings.DB_AUTO_MIGRATE:
        await _init_schema()
        return

    import asyncpg

    url = make_url(settings.database_url)
    lock_database = (
        settings.DB_MAINTENANCE_DB if settings.DB_AUTO_CREATE_DATABASE else url.database
    )
    lock_conn = await asyncpg.connect(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=lock_database,
    )
    try:
        # advisory lock 是集群级（跨库跨 session），维护库上持锁即可保护目标库的初始化
        await lock_conn.execute("SELECT pg_advisory_lock($1)", _STARTUP_LOCK_KEY)

        if settings.DB_AUTO_CREATE_DATABASE:
            created = await ensure_database_exists()
            _db_logger.info("目标数据库已自动创建" if created else "目标数据库已存在")

        await _init_schema()
    finally:
        # session 级 advisory lock 在连接关闭时自动释放；显式 unlock 只是提前放行其他
        # worker。清理动作的异常绝不允许掩盖 _init_schema() 的原始错误（如迁移版本
        # 不一致）——那是启动排障的关键信息。
        try:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", _STARTUP_LOCK_KEY)
        except Exception as exc:  # noqa: BLE001 - 清理失败不影响主流程
            _db_logger.warning(
                "释放启动 advisory lock 失败（连接关闭时会自动释放）", error=str(exc)
            )
        try:
            await lock_conn.close()
        except Exception as exc:  # noqa: BLE001
            _db_logger.warning("关闭启动锁连接失败", error=str(exc))


@register_startup("database", priority=10, critical=True)
async def startup_database() -> None:
    """启动任务：建库（可选）→ schema 初始化 → 连通性探测。

    critical=True：任何一步失败都拒绝启动（DB 是核心依赖，不可降级）。
    多 worker 并发由 advisory lock 串行化（见 ``_init_schema_under_lock``）。
    """
    await _init_schema_under_lock()
    await _check_connection()


@register_shutdown("database", priority=15)
async def shutdown_database() -> None:
    """关闭任务：释放 engine 连接池。

    priority=15：降序执行下排在 token_gc(30)/exception_retention(25)/redis(20) 之后
    （这些任务可能还要用 DB），telemetry(10) 之前（OTel 最后 flush，不用 DB）。
    进程内多次 lifespan（测试场景）靠它避免池连接持续累积。
    """
    await engine.dispose()
    _db_logger.info("数据库连接池已释放")
