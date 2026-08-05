"""数据库 schema 检查与初始化（仅 Alembic，不再 create_all）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.loguru_logger import get_logger, suppress_library_logging
from app.database import engine, run_alembic_upgrade

suppress_library_logging()

logger = get_logger("db_initializer")


class DatabaseInitializer:
    """数据库初始化器：检查表完整性，缺失时执行 alembic upgrade head。"""

    def __init__(self):
        self.expected_tables = [
            "users",
            "roles",
            "permissions",
            "role_permissions",
            "user_roles",
            "exception_logs",
            "refresh_tokens",
            "audit_logs",
            "alembic_version",
        ]
        self.logger = get_logger("db_initializer")

    async def check_table_existence(self) -> Dict[str, bool]:
        """检查所有预期表的存在性。"""
        table_status: Dict[str, bool] = {}

        async with engine.connect() as conn:
            for table_name in self.expected_tables:
                try:
                    query = text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = :table_name LIMIT 1"
                    )
                    result = await conn.execute(query, {"table_name": table_name})
                    exists = result.fetchone() is not None
                    table_status[table_name] = exists
                    if exists:
                        self.logger.debug(f"表 '{table_name}' 存在")
                    else:
                        self.logger.warning(f"表 '{table_name}' 缺失")
                except SQLAlchemyError as e:
                    self.logger.error(f"检查表 '{table_name}' 时出错: {str(e)}")
                    table_status[table_name] = False

        return table_status

    async def apply_migrations(self) -> None:
        """执行 ``alembic upgrade head``。

        复用 ``app.database.run_alembic_upgrade`` 单一实现，避免 alembic 路径/配置
        在 database 与 db_initializer 两处重复（alembic.ini 定位逻辑集中维护）。
        """
        await run_alembic_upgrade()
        self.logger.info("已执行 alembic upgrade head")

    async def initialize_database(self) -> Dict[str, Any]:
        """检查表；有缺失则跑 Alembic 迁移（不 create_all）。"""
        result: Dict[str, Any] = {
            "success": False,
            "tables_checked": 0,
            "missing_tables": [],
            "migrated": False,
            "errors": [],
        }

        try:
            self.logger.info("开始数据库初始化（Alembic only）")
            table_status = await self.check_table_existence()
            result["tables_checked"] = len(table_status)

            missing_tables = [t for t, exists in table_status.items() if not exists]
            result["missing_tables"] = missing_tables
            self.logger.info(f"缺失表数: {len(missing_tables)}: {missing_tables}")

            if missing_tables:
                await self.apply_migrations()
                result["migrated"] = True
                # 再检查
                updated = await self.check_table_existence()
                still_missing = [t for t, ok in updated.items() if not ok]
                if still_missing:
                    result["errors"].append(f"迁移后仍缺失: {still_missing}")
                    self.logger.error(f"迁移后仍缺失表: {still_missing}")
                else:
                    result["success"] = True
            else:
                result["success"] = True
                self.logger.info("所有表已存在，无需迁移")

            self.logger.info("数据库初始化完成")
        except Exception as e:
            error_msg = f"数据库初始化失败: {str(e)}"
            self.logger.error(error_msg)
            result["errors"].append(error_msg)

        return result


async def initialize_database() -> Dict[str, Any]:
    """初始化数据库的便捷函数（Alembic）。"""
    return await DatabaseInitializer().initialize_database()


async def check_and_create_tables() -> Dict[str, Any]:
    """兼容旧名：检查表并在缺失时 alembic upgrade（不再 create_all）。"""
    initializer = DatabaseInitializer()
    table_status = await initializer.check_table_existence()
    missing = [t for t, ok in table_status.items() if not ok]
    migrated = False
    if missing:
        await initializer.apply_migrations()
        migrated = True
        table_status = await initializer.check_table_existence()
    return {
        "table_status": table_status,
        "migrated": migrated,
        "missing_before": missing,
    }
