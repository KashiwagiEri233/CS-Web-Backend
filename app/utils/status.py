"""应用状态检查工具。"""

from typing import Any, Dict

from sqlalchemy import text

from app.core.config import settings
from app.database import get_session


async def check_database_connection() -> Dict[str, Any]:
    """检查数据库连接状态。

    Returns:
        包含连接状态和详细信息的字典。
    """
    try:
        async with get_session() as session:
            result = await session.execute(text("SELECT 1"))
            row = result.fetchone()

            if not (row and row[0] == 1):
                return {"status": "error", "message": "Database query failed"}

            db_url = settings.DATABASE_URL or ""
            if "postgresql" in db_url:
                db_type = "PostgreSQL"
                version_result = await session.execute(text("SELECT version()"))
                version_row = version_result.fetchone()
                version = version_row[0] if version_row else "Unknown"
            elif "sqlite" in db_url:
                db_type = "SQLite"
                version_result = await session.execute(text("SELECT sqlite_version()"))
                version_row = version_result.fetchone()
                version = (
                    f"SQLite {version_row[0]}" if version_row else "SQLite Unknown"
                )
            else:
                db_type = "Unknown"
                version = "Unknown"

            return {
                "status": "connected",
                "type": db_type,
                "version": version.split(",")[0] if "," in version else version,
            }
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


async def check_redis_connection() -> Dict[str, Any]:
    """检查 Redis 连接状态。

    未配置 REDIS_URL 时返回 not_configured（视为正常，限流/缓存走内存降级）；
    已配置但 ping 失败返回 error。
    """
    if not settings.REDIS_URL:
        return {"status": "not_configured"}

    try:
        from app.core.redis_client import ping_redis

        if await ping_redis():
            return {"status": "connected"}
        return {"status": "error", "message": "Redis ping failed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def check_application_status() -> Dict[str, Any]:
    """检查应用整体状态。"""
    return {
        "application": "running",
        "database": await check_database_connection(),
        "redis": await check_redis_connection(),
    }
