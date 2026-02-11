from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings


# SQLAlchemy 2.0 风格的基类
class Base(DeclarativeBase):
    pass


# 创建异步数据库引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

# 创建异步会话工厂
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# 获取数据库会话的依赖注入函数
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
