"""钱包账本集成测试：真实 PostgreSQL 上验证双分录、余额与撤权回滚。

所有断言在事务内完成并显式回滚，不向开发库留下账本行（账本不可删除）。
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.exceptions import ConflictException
from app.core.security import async_get_password_hash
from app.database import get_session
from app.models.user import User
from app.services.wallet.ledger_service import LedgerService

pytestmark = pytest.mark.integration


async def test_ledger_transfer_double_entry_and_insufficient_balance(admin_user):
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        recipient = User(
            username=f"itest_payee_{sfx}",
            email=f"itest_payee_{sfx}@t.com",
            hashed_password=await async_get_password_hash("StrongPass1!"),
            is_active=True,
        )
        db.add(recipient)
        await db.flush()

        ledger = LedgerService(db)
        treasury, issuance = await ledger.ensure_system_accounts()
        payer_account = await ledger.ensure_user_account(admin_user)
        payee_account = await ledger.ensure_user_account(recipient.id)

        await ledger.transfer(
            from_account_id=issuance.id,
            to_account_id=payer_account.id,
            amount=1000,
            type="issue",
            business_key=f"itest:{sfx}:issue",
            actor_user_id=admin_user,
        )
        await ledger.transfer(
            from_account_id=payer_account.id,
            to_account_id=payee_account.id,
            amount=100,
            type="user_transfer",
            business_key=f"itest:{sfx}:transfer",
            actor_user_id=admin_user,
        )

        # 立即触发延迟约束，验证「已封账 + 至少两条分录 + 合计为 0」
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        assert int(payer_account.balance) == 900
        assert int(payee_account.balance) == 100
        assert int(issuance.balance) == -1000
        assert int(treasury.balance) == 0

        with pytest.raises(ConflictException):
            await ledger.transfer(
                from_account_id=payee_account.id,
                to_account_id=payer_account.id,
                amount=200,
                type="user_transfer",
                business_key=f"itest:{sfx}:overdraft",
                actor_user_id=recipient.id,
            )

        await db.rollback()
