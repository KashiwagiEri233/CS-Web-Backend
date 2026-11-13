"""组织与财务集成测试：峰账户、成员范围、调拨与对账（事务内回滚）。"""

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import ConflictException
from app.core.security import async_get_password_hash
from app.database import get_session
from app.models.organization import MemberProfile
from app.models.user import User
from app.services.organization.organization_service import OrganizationService
from app.services.wallet.finance_service import FinanceService

pytestmark = pytest.mark.integration


async def test_peak_member_and_finance_flow(admin_user):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        org = OrganizationService(db)
        finance = FinanceService(db)
        actor = (
            await db.execute(select(User).where(User.id == admin_user))
        ).scalar_one()

        peak = await org.create_peak(
            {
                "code": f"p{sfx}",
                "name": "测试峰",
                "fantasy_name": "青云峰",
                "description": "itest",
            }
        )
        member_user = User(
            username=f"itest_member_{sfx}",
            email=f"itest_member_{sfx}@t.com",
            hashed_password=await async_get_password_hash("StrongPass1!"),
            is_active=True,
        )
        db.add(member_user)
        await db.flush()

        member = await org.create_member(
            actor,
            user_id=member_user.id,
            peak_id=peak.id,
            student_id=None,
        )
        assert member["peak_id"] == peak.id
        assert member["membership_status"] == "active"

        # 峰仍有在册成员 -> 归档拒绝
        with pytest.raises(ConflictException):
            await org.archive_peak(peak.id)

        # 财务：发行到管理员账户，再从总库划拨到峰
        admin_account = await finance.ledger.ensure_user_account(actor.id)
        treasury = await finance.get_treasury()
        peak_account = await finance.repo.ensure_peak_account(peak.id)

        await finance.adjust(
            actor_id=actor.id,
            target_account_id=treasury.id,
            direction="issue",
            amount=1000,
            reason="itest issue",
            idempotency_key=f"itest:{sfx}:issue",
            request_id=None,
        )
        await finance.allocate(
            actor_id=actor.id,
            from_account_id=treasury.id,
            to_account_id=peak_account.id,
            amount=500,
            reason="itest allocate",
            operation_kind="allocation",
            idempotency_key=f"itest:{sfx}:alloc",
            request_id=None,
        )
        assert int(treasury.balance) == 500
        assert int(peak_account.balance) == 500

        report = await finance.reconcile(triggered_by=actor.id, commit=False)
        assert report["status"] == "ok"
        assert report["counts"]["unbalanced_transactions"] == 0
        assert report["counts"]["circulation_difference"] == 0

        await db.rollback()
