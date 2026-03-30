"""
应用状态检查工具
"""

from typing import Dict, Any
from sqlalchemy import text

from app.database import get_db
from app.core.config import settings


async def check_database_connection() -> Dict[str, Any]:
    """
    检查数据库连接状态

    Returns:
        包含连接状态和详细信息的字典
    """
    try:
        async for session in get_db():
            try:
                # 执行简单查询测试连接
                result = await session.execute(text("SELECT 1"))
                row = result.fetchone()

                if row and row[0] == 1:
                    # 获取数据库类型信息
                    if "postgresql" in settings.DATABASE_URL:
                        db_type = "PostgreSQL"
                        # 获取PostgreSQL版本
                        version_result = await session.execute(text("SELECT version()"))
                        version_row = version_result.fetchone()
                        version = version_row[0] if version_row else "Unknown"
                    elif "sqlite" in settings.DATABASE_URL:
                        db_type = "SQLite"
                        # 获取SQLite版本
                        version_result = await session.execute(
                            text("SELECT sqlite_version()")
                        )
                        version_row = version_result.fetchone()
                        version = (
                            f"SQLite {version_row[0]}"
                            if version_row
                            else "SQLite Unknown"
                        )
                    else:
                        db_type = "Unknown"
                        version = "Unknown"

                    return {
                        "status": "connected",
                        "type": db_type,
                        "version": (
                            version.split(",")[0] if "," in version else version
                        ),  # 只取版本号前面的主要部分
                    }
                else:
                    return {"status": "error", "message": "Database query failed"}
            except Exception as e:
                return {"status": "error", "message": str(e)}
            finally:
                await session.close()

    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


async def check_application_status() -> Dict[str, Any]:
    """
    检查应用整体状态

    Returns:
        包含各组件状态的字典
    """
    return {
        "application": "running",
        "database": await check_database_connection(),
    }
