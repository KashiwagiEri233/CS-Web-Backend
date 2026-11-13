#!/usr/bin/env python3
"""P6 统一 RBAC 种子：权限目录、内置角色、默认 member 绑定与受保护角色。

幂等：复用 app.services.rbac.rbac_init.initialize_rbac，不提升任何普通用户。
支持 --dry-run（只打印事实，不落库）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_ROOT))

from app.database import get_session  # noqa: E402
from app.services.rbac.rbac_init import initialize_rbac  # noqa: E402


async def _run(dry_run: bool) -> dict:
    async with get_session() as db:
        if dry_run:
            report = await initialize_rbac(db)
            await db.rollback()
            return {**report, "status": "dry-run"}
        report = await initialize_rbac(db)
        await db.commit()
        return {**report, "status": "committed"}


def main() -> int:
    parser = argparse.ArgumentParser(description="幂等初始化统一 RBAC")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    report = asyncio.run(_run(args.dry_run))
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("success", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
