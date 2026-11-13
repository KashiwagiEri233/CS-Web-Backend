#!/usr/bin/env python3
"""为登录后写链路 E2E 准备固定测试账号（仅开发/演练库）。

幂等：重复执行会重置密码、补齐成员档案/角色绑定，并把钱包补足到初始余额。
凭据写入仓库外文件，由 Playwright 通过环境变量读取，不进入代码库。

安全：必须显式 `--confirm-target`；库名含 prod 时拒绝执行。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Optional

# 直接以脚本路径运行时，把后端根目录加入 sys.path 后再导入 app。
BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import insert, select

from app.core.config import settings
from app.core.security import async_get_password_hash
from app.database import get_session
from app.models.organization import MemberProfile
from app.models.role import Role
from app.models.user import User, user_roles
from app.services.wallet.finance_service import FinanceService
from app.services.wallet.ledger_service import LedgerService

DEFAULT_OUT = Path(r"D:\00025927xiangmu\rebuild\e2e-credentials.json")
START_BALANCE = 100


async def _provision(username: str, email: str, password: str) -> dict:
    async with get_session() as db:
        admin = (
            await db.execute(
                select(User)
                .where(User.is_superuser.is_(True), User.deleted_at.is_(None))
                .order_by(User.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if admin is None:
            raise RuntimeError("未找到超级管理员，无法准备测试账号资金")

        hashed = await async_get_password_hash(password)
        user = (
            await db.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                username=username,
                email=email,
                hashed_password=hashed,
                display_name="E2E Runner",
                is_active=True,
            )
            db.add(user)
            await db.flush()
        else:
            user.email = email
            user.hashed_password = hashed
            user.is_active = True
            user.deleted_at = None
            user.display_name = user.display_name or "E2E Runner"

        profile = (
            await db.execute(
                select(MemberProfile).where(MemberProfile.user_id == user.id)
            )
        ).scalar_one_or_none()
        if profile is None:
            db.add(
                MemberProfile(
                    user_id=user.id,
                    membership_status="active",
                )
            )
        elif profile.membership_status != "active":
            profile.membership_status = "active"

        role = (
            await db.execute(select(Role).where(Role.name == "member"))
        ).scalar_one_or_none()
        if role is not None:
            binding = (
                await db.execute(
                    select(user_roles.c.id).where(
                        user_roles.c.user_id == user.id,
                        user_roles.c.role_id == role.id,
                    )
                )
            ).first()
            if binding is None:
                await db.execute(
                    insert(user_roles).values(
                        user_id=user.id,
                        role_id=role.id,
                        scope_type="own",
                        scope_peak_id=None,
                        created_by=admin.id,
                    )
                )

        ledger = LedgerService(db)
        account = await ledger.ensure_user_account(user.id)
        if int(account.balance) < START_BALANCE:
            await FinanceService(db).adjust(
                actor_id=admin.id,
                target_account_id=account.id,
                direction="issue",
                amount=START_BALANCE - int(account.balance),
                reason="E2E 测试资金",
                idempotency_key=f"e2e-provision:{uuid.uuid4().hex}",
                request_id=None,
            )

        await db.commit()
        balance = int(account.balance)
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "password": password,
            "balance": balance,
            "database": settings.DATABASE_NAME,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 E2E 固定测试账号")
    parser.add_argument("--username", default="e2e_runner")
    # 注意：pydantic EmailStr 拒绝 example/invalid/localhost/test 等保留域，
    # 这里使用普通可解析域名，仅用于开发库测试账号。
    parser.add_argument("--email", default="e2e_runner@e2e-runner.dev")
    parser.add_argument("--password", default="E2ePass!2026")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--confirm-target", action="store_true")
    args = parser.parse_args()

    if "prod" in settings.DATABASE_NAME.lower():
        print("[e2e] 拒绝执行：目标库名包含 prod")
        return 2
    if not args.confirm_target:
        print("[e2e] 拒绝执行：缺少 --confirm-target")
        return 2

    result: Optional[dict] = asyncio.run(
        _provision(args.username, args.email, args.password)
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
