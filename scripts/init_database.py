#!/usr/bin/env python3
"""数据库初始化脚本：检查表完整性，缺失时执行 alembic upgrade head。

不再使用 Base.metadata.create_all。Schema 唯一来源 = Alembic 迁移链。

用法::

    python scripts/init_database.py
"""

import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

os.environ.setdefault("ENV_FILE", ".env")

from app.core.loguru_logger import get_logger
from app.utils.db_initializer import initialize_database

logger = get_logger("db_init_script")


async def main() -> None:
    print("=" * 60)
    print("数据库初始化（Alembic only）")
    print("=" * 60)
    result = await initialize_database()
    print(result)
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
