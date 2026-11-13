"""任务托管结算集成测试（真实 PostgreSQL）。

覆盖：审核通过原子托管、单人验收全额给队长、团队奖励只进队长、
奖励与退款互斥、重复验收不重复发放。全部在事务内回滚，不留下账本行。
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.exceptions import ConflictException, AuthorizationException
from app.core.security import async_get_password_hash
from app.core.timezone import now_utc
from app.database import get_session
from app.models.organization import MemberProfile
from app.models.user import User
from app.schemas.task import (
    ClaimCreate,
    SubmissionCreate,
    SubmissionReviewCreate,
    TaskCreate,
    TaskReviewCreate,
    TeamCreate,
)
from app.services.task.review_service import TaskReviewService
from app.services.task.task_service import TaskService
from app.services.task.team_service import TeamService
from app.services.wallet.ledger_service import LedgerService
from app.repositories.wallet_repo import WalletRepository

pytestmark = pytest.mark.integration


async def _make_user(db, sfx: str, tag: str) -> User:
    user = User(
        username=f"task_{tag}_{sfx}",
        email=f"task_{tag}_{sfx}@t.com",
        hashed_password=await async_get_password_hash("StrongPass1!"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_member(db, user: User) -> None:
    db.add(MemberProfile(user_id=user.id, membership_status="active"))
    await db.flush()


async def _balance(db, user_id: int) -> int:
    account = await WalletRepository(db).get_user_account(user_id)
    if account is None:
        return 0
    await db.refresh(account)
    return int(account.balance)


async def _escrow_balance(db, task_id: int) -> int:
    account = await WalletRepository(db).ensure_task_escrow(task_id)
    await db.refresh(account)
    return int(account.balance)


async def test_single_task_settles_reward_once(admin_user):
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "pub")
        leader = await _make_user(db, sfx, "leader")
        reviewer = await _make_user(db, sfx, "reviewer")
        await _make_member(db, leader)

        ledger = LedgerService(db)
        _treasury, issuance = await ledger.ensure_system_accounts()
        publisher_account = await ledger.ensure_user_account(publisher.id)
        await ledger.transfer(
            from_account_id=issuance.id,
            to_account_id=publisher_account.id,
            amount=1000,
            type="issue",
            business_key=f"itest:{sfx}:issue",
            actor_user_id=admin_user,
        )

        task_service = TaskService(db)
        review_service = TaskReviewService(db)
        task = await task_service.create_task(
            actor=publisher,
            data=TaskCreate(
                title=f"单人任务 {sfx}",
                description="集成测试任务完整描述",
                reward_total="300",
                execution_mode="single",
                max_members=1,
                deadline=now_utc() + timedelta(days=1),
                visibility="members",
            ),
            idempotency_key=f"create-{sfx}",
        )
        await task_service.request_review(
            actor=publisher,
            task_id=task["id"],
            idempotency_key=f"review-req-{sfx}",
        )
        approved = await review_service.review_task(
            actor=reviewer,
            task_id=task["id"],
            data=TaskReviewCreate(decision="approve"),
            idempotency_key=f"review-{sfx}",
        )
        assert approved["status"] == "published"
        assert await _balance(db, publisher.id) == 700
        assert await _escrow_balance(db, task["id"]) == 300

        claim = await task_service.claim_task(
            actor=leader,
            task_id=task["id"],
            data=ClaimCreate(),
            idempotency_key=f"claim-{sfx}",
        )
        assert claim["status"] == "active"
        submitted = await task_service.submit_claim(
            actor=leader,
            claim_id=claim["id"],
            data=SubmissionCreate(description="已完成任务成果说明文本"),
            idempotency_key=f"submit-{sfx}",
        )
        submission_id = submitted["submission"]["id"]

        result = await review_service.review_submission(
            actor=reviewer,
            submission_id=submission_id,
            data=SubmissionReviewCreate(decision="approve"),
            idempotency_key=f"accept-{sfx}",
        )
        assert result["status"] == "completed"
        assert await _balance(db, leader.id) == 300
        assert await _balance(db, publisher.id) == 700
        assert await _escrow_balance(db, task["id"]) == 0

        with pytest.raises(ConflictException):
            await review_service.review_submission(
                actor=reviewer,
                submission_id=submission_id,
                data=SubmissionReviewCreate(decision="approve"),
                idempotency_key=f"accept-again-{sfx}",
            )

        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await db.rollback()


async def test_team_reward_goes_only_to_captain(admin_user):
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "tpub")
        captain = await _make_user(db, sfx, "captain")
        worker = await _make_user(db, sfx, "worker")
        reviewer = await _make_user(db, sfx, "treviewer")
        await _make_member(db, captain)
        await _make_member(db, worker)

        ledger = LedgerService(db)
        _treasury, issuance = await ledger.ensure_system_accounts()
        publisher_account = await ledger.ensure_user_account(publisher.id)
        await ledger.transfer(
            from_account_id=issuance.id,
            to_account_id=publisher_account.id,
            amount=1000,
            type="issue",
            business_key=f"itest:{sfx}:issue",
            actor_user_id=admin_user,
        )

        team_service = TeamService(db)
        team = await team_service.create_team(
            actor=captain,
            data=TeamCreate(name=f"队伍 {sfx}", invitee_user_ids=[worker.id]),
            idempotency_key=f"team-{sfx}",
        )
        invitations = await team_service.list_pending_invitations(actor=worker)
        await team_service.respond_invitation(
            actor=worker,
            invitation_id=invitations[0][0].id,
            accept=True,
            idempotency_key=f"join-{sfx}",
        )

        task_service = TaskService(db)
        review_service = TaskReviewService(db)
        task = await task_service.create_task(
            actor=publisher,
            data=TaskCreate(
                title=f"团队任务 {sfx}",
                description="团队集成测试任务描述",
                reward_total="300",
                execution_mode="team",
                max_members=3,
                deadline=now_utc() + timedelta(days=1),
                visibility="members",
            ),
            idempotency_key=f"create-{sfx}",
        )
        await task_service.request_review(
            actor=publisher, task_id=task["id"], idempotency_key=f"req-{sfx}"
        )
        await review_service.review_task(
            actor=reviewer,
            task_id=task["id"],
            data=TaskReviewCreate(decision="approve"),
            idempotency_key=f"review-{sfx}",
        )
        assert await _balance(db, publisher.id) == 700
        assert await _escrow_balance(db, task["id"]) == 300

        claim = await task_service.claim_task(
            actor=captain,
            task_id=task["id"],
            data=ClaimCreate(team_id=team["id"]),
            idempotency_key=f"claim-{sfx}",
        )
        assert len(claim["members"]) == 2
        submission = await task_service.submit_claim(
            actor=captain,
            claim_id=claim["id"],
            data=SubmissionCreate(description="团队完成任务成果说明文本"),
            idempotency_key=f"submit-{sfx}",
        )
        await review_service.review_submission(
            actor=reviewer,
            submission_id=submission["submission"]["id"],
            data=SubmissionReviewCreate(decision="approve"),
            idempotency_key=f"accept-{sfx}",
        )
        assert await _balance(db, captain.id) == 300
        assert await _balance(db, worker.id) == 0
        assert await _escrow_balance(db, task["id"]) == 0

        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await db.rollback()


async def test_force_close_refunds_and_blocks_acceptance(admin_user):
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "fpub")
        leader = await _make_user(db, sfx, "fleader")
        reviewer = await _make_user(db, sfx, "freviewer")
        await _make_member(db, leader)

        ledger = LedgerService(db)
        _treasury, issuance = await ledger.ensure_system_accounts()
        publisher_account = await ledger.ensure_user_account(publisher.id)
        await ledger.transfer(
            from_account_id=issuance.id,
            to_account_id=publisher_account.id,
            amount=1000,
            type="issue",
            business_key=f"itest:{sfx}:issue",
            actor_user_id=admin_user,
        )

        task_service = TaskService(db)
        review_service = TaskReviewService(db)
        task = await task_service.create_task(
            actor=publisher,
            data=TaskCreate(
                title=f"退款任务 {sfx}",
                description="强制结项退款测试描述",
                reward_total="300",
                execution_mode="single",
                max_members=1,
                deadline=now_utc() + timedelta(days=1),
                visibility="members",
            ),
            idempotency_key=f"create-{sfx}",
        )
        await task_service.request_review(
            actor=publisher, task_id=task["id"], idempotency_key=f"req-{sfx}"
        )
        await review_service.review_task(
            actor=reviewer,
            task_id=task["id"],
            data=TaskReviewCreate(decision="approve"),
            idempotency_key=f"review-{sfx}",
        )
        claim = await task_service.claim_task(
            actor=leader,
            task_id=task["id"],
            data=ClaimCreate(),
            idempotency_key=f"claim-{sfx}",
        )
        await review_service.force_close(
            actor=reviewer,
            task_id=task["id"],
            reason="管理员强制结项退款",
            idempotency_key=f"force-{sfx}",
        )
        assert await _balance(db, publisher.id) == 1000
        assert await _balance(db, leader.id) == 0
        assert await _escrow_balance(db, task["id"]) == 0

        with pytest.raises(ConflictException):
            await task_service.submit_claim(
                actor=leader,
                claim_id=claim["id"],
                data=SubmissionCreate(description="已退款后不应再提交成果说明"),
                idempotency_key=f"submit-after-close-{sfx}",
            )

        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await db.rollback()


async def test_self_review_forbidden(admin_user):
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "self")
        await _make_member(db, publisher)
        task_service = TaskService(db)
        review_service = TaskReviewService(db)
        task = await task_service.create_task(
            actor=publisher,
            data=TaskCreate(
                title=f"自审任务 {sfx}",
                description="禁止自审集成测试描述",
                reward_total="100",
                execution_mode="single",
                max_members=1,
                deadline=now_utc() + timedelta(days=1),
                visibility="members",
            ),
            idempotency_key=f"create-{sfx}",
        )
        await task_service.request_review(
            actor=publisher, task_id=task["id"], idempotency_key=f"req-{sfx}"
        )
        with pytest.raises(AuthorizationException):
            await review_service.review_task(
                actor=publisher,
                task_id=task["id"],
                data=TaskReviewCreate(decision="approve"),
                idempotency_key=f"self-review-{sfx}",
            )
        await db.rollback()
