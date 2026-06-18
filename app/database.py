from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# SQLAlchemy 2.0 风格的基类
class Base(DeclarativeBase):
    pass


# 创建异步数据库引擎
# 连接池参数由 Settings 驱动（见 config.py DB_POOL_*）：生产下 pool_pre_ping 防陈旧连接，
# pool_recycle 主动回收长连接，pool_size/max_overflow 控制并发上限。
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def ensure_database_exists() -> bool:
    """若目标数据库不存在则创建。

    Postgres 不会自动建库，这里连接到维护库（默认 postgres）检查并 CREATE DATABASE。
    返回 True 表示本次新建，False 表示已存在或未配置。
    """
    import re
    import asyncpg
    from sqlalchemy.engine import make_url

    url = make_url(settings.DATABASE_URL)
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
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# 在 FastAPI 依赖体系之外安全使用会话（worker / 脚本 / 后台任务 / 队列消费者）。
# 路由用 Depends(get_db)，非请求上下文用 `async with get_session() as db:`。
@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """提供一个受管理的异步会话。

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
