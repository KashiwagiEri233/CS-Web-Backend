"""测试用 Alembic 辅助：集成测试建表唯一路径（禁止 create_all）。"""

from __future__ import annotations

import asyncio
from pathlib import Path


async def upgrade_schema_to_head() -> None:
    """在当前 Settings 指向的库上执行 ``alembic upgrade head``。

    幂等：已是 head 时 no-op。需在 DB 可用时调用。
    """
    from alembic import command
    from alembic.config import Config

    def _upgrade() -> None:
        ini = Path(__file__).resolve().parent.parent / "alembic.ini"
        command.upgrade(Config(str(ini)), "head")

    await asyncio.to_thread(_upgrade)
