"""财务读模型与峰间调拨集成测试（事务内回滚）。"""

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import ConflictException, ValidationException
from app.core.security import async_get_password_hash
from app.database import get_session
from app.models.user import User
from app.services.organization.organization_service import OrganizationService
from app.services.wallet.finance_query_service import FinanceQueryService
from app.services.wallet.finance_service import FinanceService

pytestmark = pytest.mark.integration


async def test_finance_read_models_and_peak_transfer(admin_user):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        org = OrganizationService(db)
        finance = FinanceService(db)
        query = FinanceQueryService(db)
        actor = (
            await db.execute(select(User).where(User.id == admin_user))
        ).scalar_one()

        before = await query.stats(actor)

        peak_a = await org.create_peak(
            {"code": f"fa{sfx}", "name": "甲峰", "fantasy_name": "青云峰"}
        )
        peak_b = await org.create_peak(
            {"code": f"fb{sfx}", "name": "乙峰", "fantasy_name": "紫霄峰"}
        )
        member_user = User(
            username=f"fin_member_{sfx}",
            email=f"fin_member_{sfx}@t.com",
            hashed_password=await async_get_password_hash("StrongPass1!"),
            is_active=True,
        )
        db.add(member_user)
        await db.flush()
        member = await org.create_member(
            actor,
            user_id=member_user.id,
            peak_id=peak_a.id,
            student_id=f"S{sfx[:6]}",
        )

        treasury = await finance.get_treasury()
        peak_a_account = await finance.repo.ensure_peak_account(peak_a.id)
        peak_b_account = await finance.repo.ensure_peak_account(peak_b.id)
        member_account = await finance.ledger.ensure_user_account(member_user.id)

        await finance.adjust(
            actor_id=actor.id,
            target_account_id=treasury.id,
            direction="issue",
            amount=1000,
            reason="itest read issue",
            idempotency_key=f"itest:{sfx}:issue",
            request_id=None,
        )
        await finance.allocate(
            actor_id=actor.id,
            from_account_id=treasury.id,
            to_account_id=peak_a_account.id,
            amount=500,
            reason="itest allocate a",
            operation_kind="allocation",
            idempotency_key=f"itest:{sfx}:alloc-a",
            request_id=None,
        )
        await finance.allocate(
            actor_id=actor.id,
            from_account_id=treasury.id,
            to_account_id=peak_b_account.id,
            amount=200,
            reason="itest allocate b",
            operation_kind="allocation",
            idempotency_key=f"itest:{sfx}:alloc-b",
            request_id=None,
        )
        await finance.allocate(
            actor_id=actor.id,
            from_account_id=peak_a_account.id,
            to_account_id=member_account.id,
            amount=100,
            reason="itest member allocation",
            operation_kind="member_allocation",
            idempotency_key=f"itest:{sfx}:member",
            request_id=None,
        )
        await finance.peak_transfer(
            actor_id=actor.id,
            from_peak_id=peak_a.id,
            to_peak_id=peak_b.id,
            amount=50,
            reason="itest peak transfer",
            idempotency_key=f"itest:{sfx}:transfer",
            request_id=None,
        )

        # 峰读模型：名称、余额与成员数
        peaks, _ = await query.list_peaks(actor, 0, 200)
        by_id = {row["peak_id"]: row for row in peaks}
        assert by_id[peak_a.id]["peak_name"] == "青云峰"
        assert by_id[peak_a.id]["balance"] == 350
        assert by_id[peak_a.id]["member_count"] == 1
        assert by_id[peak_b.id]["balance"] == 250

        single = await query.get_peak(actor, peak_a.id)
        assert single["peak_code"] == f"fa{sfx}"
        assert single["balance"] == 350

        # 峰成员资金摘要：最小披露 + 余额
        members, member_total = await query.list_peak_members(actor, peak_a.id, 0, 100)
        assert member_total == 1
        assert members[0]["user_id"] == member_user.id
        assert members[0]["display_name"] == f"fin_member_{sfx}"
        assert members[0]["balance"] == 100

        detail = await query.get_user_detail(actor, member_user.id)
        assert detail["member_id"] == member["id"]
        assert detail["peak_name"] == "青云峰"
        assert detail["balance"] == 100

        # 流水：分录带展示名与所属峰
        rows, total = await query.list_transactions(
            actor,
            type_=None,
            account_id=peak_a_account.id,
            skip=0,
            limit=50,
        )
        assert total == 3
        member_rows = [
            row
            for row in rows
            if any(entry["account_id"] == member_account.id for entry in row["entries"])
        ]
        assert member_rows
        entry = next(
            item
            for item in member_rows[0]["entries"]
            if item["account_id"] == member_account.id
        )
        assert entry["owner_name"] == f"fin_member_{sfx}"
        assert entry["peak_name"] == "青云峰"

        transfers, transfer_total = await query.list_transactions(
            actor,
            type_="peak_transfer",
            account_id=None,
            skip=0,
            limit=10,
        )
        assert transfer_total == 1
        assert transfers[0]["business_key"].startswith("peak_transfer:")

        # 统计：按账户类型增量核对
        after = await query.stats(actor)
        assert after["treasury"] - before["treasury"] == 300
        assert after["peak_total"] - before["peak_total"] == 600
        assert after["user_total"] - before["user_total"] == 100
        assert after["issuance"] - before["issuance"] == -1000

        with pytest.raises(ValidationException):
            await finance.peak_transfer(
                actor_id=actor.id,
                from_peak_id=peak_a.id,
                to_peak_id=peak_a.id,
                amount=10,
                reason="itest same peak",
                idempotency_key=f"itest:{sfx}:same",
                request_id=None,
            )

        report = await finance.reconcile(triggered_by=actor.id, commit=False)
        assert report["status"] == "ok"

        await db.rollback()


async def test_finance_reversal_restores_balances(admin_user):
    """冲正按原分录取反：余额回到冲正前，且同一交易只能冲正一次。"""
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        org = OrganizationService(db)
        finance = FinanceService(db)
        actor = (
            await db.execute(select(User).where(User.id == admin_user))
        ).scalar_one()

        peak = await org.create_peak(
            {"code": f"fr{sfx}", "name": "冲正峰", "fantasy_name": "回澜峰"}
        )
        treasury = await finance.get_treasury()
        treasury_before = int(treasury.balance)
        peak_account = await finance.repo.ensure_peak_account(peak.id)

        await finance.adjust(
            actor_id=actor.id,
            target_account_id=treasury.id,
            direction="issue",
            amount=300,
            reason="itest reversal issue",
            idempotency_key=f"itest:{sfx}:r-issue",
            request_id=None,
        )
        allocation = await finance.allocate(
            actor_id=actor.id,
            from_account_id=treasury.id,
            to_account_id=peak_account.id,
            amount=120,
            reason="itest reversal allocation",
            operation_kind="allocation",
            idempotency_key=f"itest:{sfx}:r-alloc",
            request_id=None,
        )
        assert int((await finance.repo.get_peak_account(peak.id)).balance) == 120

        reversal = await finance.reverse(
            actor_id=actor.id,
            transaction_id=allocation["transaction_id"],
            reason="itest reversal",
            idempotency_key=f"itest:{sfx}:reverse",
            request_id=None,
        )
        assert reversal["original_transaction_id"] == allocation["transaction_id"]
        assert int(reversal["amount"]) == 120

        assert int((await finance.repo.get_peak_account(peak.id)).balance) == 0
        assert int((await finance.get_treasury()).balance) == treasury_before + 300

        with pytest.raises(ConflictException):
            await finance.reverse(
                actor_id=actor.id,
                transaction_id=allocation["transaction_id"],
                reason="itest double reversal",
                idempotency_key=f"itest:{sfx}:reverse-again",
                request_id=None,
            )

        report = await finance.reconcile(triggered_by=actor.id, commit=False)
        assert report["status"] == "ok"

        await db.rollback()
