#!/usr/bin/env python3
"""P6 业务种子：系统账户 + 用户零余额账户 + 有效峰账户。

只创建账户，不发行资金；测试资金必须由显式测试 fixture/脚本注入。
支持 --dry-run（只统计缺口，不写库）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.database import get_session  # noqa: E402
from app.models.organization import Peak  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repositories.wallet_repo import WalletRepository  # noqa: E402
from app.services.wallet.ledger_service import LedgerService  # noqa: E402


async def _run(dry_run: bool) -> dict:
    report = {
        "status": "dry-run" if dry_run else "committed",
        "system_accounts": 0,
        "user_accounts_created": 0,
        "user_accounts_existing": 0,
        "peak_accounts_created": 0,
        "peak_accounts_existing": 0,
    }
    async with get_session() as db:
        ledger = LedgerService(db)
        repo = WalletRepository(db)
        users = (
            await db.execute(select(User.id).where(User.deleted_at.is_(None)))
        ).scalars().all()
        peaks = (
            await db.execute(select(Peak.id).where(Peak.archived_at.is_(None)))
        ).scalars().all()

        if not dry_run:
            await ledger.ensure_system_accounts()
            report["system_accounts"] = 2

        for user_id in users:
            existing = await repo.get_user_account(user_id)
            if existing is None:
                report["user_accounts_created"] += 1
                if not dry_run:
                    await ledger.ensure_user_account(user_id)
            else:
                report["user_accounts_existing"] += 1
        for peak_id in peaks:
            existing = await repo.get_peak_account(peak_id)
            if existing is None:
                report["peak_accounts_created"] += 1
                if not dry_run:
                    await repo.ensure_peak_account(peak_id)
            else:
                report["peak_accounts_existing"] += 1

        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="创建系统/用户/峰零余额钱包账户")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    report = asyncio.run(_run(args.dry_run))
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
