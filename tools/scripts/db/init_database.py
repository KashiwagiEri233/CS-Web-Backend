#!/usr/bin/env python3
"""数据库初始化脚本：检查表完整性，缺失时执行 alembic upgrade head。

不再使用 Base.metadata.create_all。Schema 唯一来源 = Alembic 迁移链。

用法::

    python tools/scripts/db/init_database.py              # 默认 .env（会要求确认）
    python tools/scripts/db/init_database.py --env 2      # 测试环境 .env.test
    python tools/scripts/db/init_database.py --env 1 -y   # 开发环境，跳过确认
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 脚本现已位于 tools/scripts/，需向上三级到达仓库根。
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.core.loguru_logger import get_logger  # noqa: E402

logger = get_logger("db_init_script")

# 与 run.py 一致的环境配置文件映射
_ENV_FILES = {
    1: ".env.development",
    2: ".env.test",
    3: ".env",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="数据库初始化（Alembic only）")
    parser.add_argument(
        "--env",
        type=int,
        choices=[1, 2, 3],
        default=3,
        help="环境配置: 1=开发(.env.development) 2=测试(.env.test) 3=生产(.env，默认)",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="跳过确认提示")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    env_file = _ENV_FILES[args.env]
    os.environ.setdefault("ENV_FILE", env_file)

    # 默认指向生产配置（--env 3），误在本地跑会直接操作生产库，强制确认；
    # 测试/开发环境或非交互场景（CI 用 -y）不拦。
    if args.env == 3 and not args.yes:
        from app.core.config import settings  # 延迟 import：需先设 ENV_FILE

        answer = input(
            f"即将对【生产配置 {env_file}】指向的数据库 "
            f"({settings.DATABASE_HOST}/{settings.DATABASE_NAME}) 执行初始化，确认？[y/N] "
        )
        if answer.strip().lower() != "y":
            logger.info("已取消")
            return

    from app.utils.db_initializer import initialize_database

    logger.info("数据库初始化开始", env_file=env_file)
    result = await initialize_database()
    if not result.get("success"):
        logger.error("数据库初始化失败", result=result)
        sys.exit(1)
    logger.info("数据库初始化完成", result=result)


if __name__ == "__main__":
    asyncio.run(main())
