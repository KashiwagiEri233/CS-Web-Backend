"""Pytest 全局配置：在导入 ``app.*`` 前强制隔离测试基础设施。

测试绝不能继承开发/生产 ``.env`` 中的数据库和 Redis 地址。CI 可通过
``TEST_DATABASE_URL`` / ``TEST_REDIS_URL`` 显式指定临时服务；本地默认只读取
仓库内的 ``.env.test``。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


ROOT_DIR = Path(__file__).resolve().parent.parent
TEST_ENV_FILE = ROOT_DIR / ".env.test"

_DATABASE_ENV_KEYS = (
    "DATABASE_URL",
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
)


def _configure_test_environment() -> None:
    """锁定测试配置，并拒绝任何看起来不像测试库的数据库地址。"""
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    test_redis_url = os.environ.get("TEST_REDIS_URL")

    # ENV_FILE 总是指向仓库内测试配置，避免当前工作目录或宿主 .env 漂移。
    os.environ["ENV_FILE"] = str(TEST_ENV_FILE)

    # 清除可能从 shell/Jenkins 节点继承的真实库拆分配置。
    for key in _DATABASE_ENV_KEYS:
        os.environ.pop(key, None)

    env_values = dotenv_values(TEST_ENV_FILE)
    database_url = test_database_url or env_values.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("测试配置缺少 DATABASE_URL 或 TEST_DATABASE_URL")

    database_name = make_url(str(database_url)).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(
            "拒绝运行测试：数据库名称必须包含 'test'，" f"当前名称为 {database_name!r}"
        )

    os.environ["DATABASE_URL"] = str(database_url)
    os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-at-least-32-bytes"
    os.environ["TOTP_ENCRYPTION_KEY"] = "test-totp-encryption-key-at-least-32-bytes"
    os.environ["TESTING"] = "True"

    if test_redis_url:
        os.environ["REDIS_URL"] = test_redis_url
    else:
        os.environ.pop("REDIS_URL", None)


_configure_test_environment()


def integration_db_unavailable(message: str) -> None:
    """本地允许跳过可选 DB 测试；CI/显式严格模式下直接失败。"""
    required = os.environ.get("REQUIRE_INTEGRATION_DB", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if required:
        pytest.fail(message)
    pytest.skip(message)


def integration_redis_unavailable(message: str) -> None:
    """本地允许跳过 Redis 测试；CI/显式严格模式下直接失败。"""
    required = os.environ.get("REQUIRE_INTEGRATION_REDIS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if required:
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture
async def integration_db_ready():
    """确保真实 PostgreSQL 可用且 schema 已迁移到 Alembic head。"""
    from sqlalchemy import text

    from app.database import get_session
    from tests._alembic_helpers import upgrade_schema_to_head

    try:
        async with get_session() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:
        integration_db_unavailable(f"PostgreSQL 集成服务不可用: {exc}")

    await upgrade_schema_to_head()
    yield


@pytest.fixture
async def integration_redis_client():
    """提供真实 Redis 客户端，并在不可用时遵循严格集成测试策略。"""
    from redis.asyncio import from_url

    redis_url = os.environ.get("TEST_REDIS_URL") or os.environ.get("REDIS_URL")
    if not redis_url:
        integration_redis_unavailable("Redis 集成测试缺少 TEST_REDIS_URL/REDIS_URL")

    client = from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        integration_redis_unavailable(f"Redis 集成服务不可用: {exc}")

    try:
        yield client
    finally:
        await client.aclose()
