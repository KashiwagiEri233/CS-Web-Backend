import asyncio
import os
from typing import AsyncGenerator, Dict

import pytest
import pytest_asyncio
from httpx import AsyncClient

# 设置测试环境变量
os.environ["ENV_FILE"] = ".env.test"

from app.main import app
from app.core.config import settings
from app.database import get_db, engine, Base, AsyncSessionLocal
from app.models import User
from app.core.security import get_password_hash


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def setup_database():
    """设置测试数据库"""
    # 使用SQLite测试数据库
    import os
    if os.path.exists("test.db"):
        os.remove("test.db")
    
    from sqlalchemy.ext.asyncio import create_async_engine
    test_engine = create_async_engine(settings.DATABASE_URL, echo=False)
    
    # 创建所有表
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # 清理数据库
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    # 删除测试数据库文件
    if os.path.exists("test.db"):
        os.remove("test.db")


@pytest_asyncio.fixture
async def db_session(setup_database):
    """创建数据库会话"""
    from sqlalchemy.ext.asyncio import create_async_engine
    test_engine = create_async_engine(settings.DATABASE_URL, echo=False)
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """创建测试客户端"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def superuser_token_headers(client: AsyncClient) -> Dict[str, str]:
    """创建超级用户并返回其令牌头"""
    import uuid
    unique_id = str(uuid.uuid4())[:8]  # 生成唯一ID
    
    # 创建超级用户
    user_data = {
        "username": f"superuser_{unique_id}",  # 使用唯一名称
        "email": f"super_{unique_id}@example.com",  # 使用唯一邮箱
        "password": "t",  # 使用极简密码避免bcrypt问题
        "is_active": True
    }
    
    register_response = await client.post(
        "/api/v1/auth/register",
        params=user_data
    )
    assert register_response.status_code == 200
    
    # 手动设置为超级用户（通常通过数据库直接操作）
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import AsyncSession
    
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.username == f"superuser_{unique_id}"))
        user_obj = user.scalar_one_or_none()
        if user_obj:
            user_obj.is_superuser = True
            await session.commit()
    
    # 登录获取令牌
    login_response = await client.post(
        "/api/v1/auth/login-json",
        json={"username": f"superuser_{unique_id}", "password": "t"}
    )
    
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def normal_user_token_headers(client: AsyncClient) -> Dict[str, str]:
    """创建普通用户并返回其令牌头"""
    import uuid
    unique_id = str(uuid.uuid4())[:8]  # 生成唯一ID
    
    # 创建普通用户
    user_data = {
        "username": f"normaluser_{unique_id}",
        "email": f"normal_{unique_id}@example.com",
        "password": "t",  # 使用极简密码避免bcrypt问题
        "is_active": True
    }
    
    register_response = await client.post(
        "/api/v1/auth/register",
        params=user_data
    )
    assert register_response.status_code == 200
    
    # 登录获取令牌
    login_response = await client.post(
        "/api/v1/auth/login-json",
        json={"username": f"normaluser_{unique_id}", "password": "t"}
    )
    
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    
    return {"Authorization": f"Bearer {token}"}