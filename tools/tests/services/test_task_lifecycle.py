"""P6 任务/团队生命周期集成测试（真实 PostgreSQL，事务内回滚）。

覆盖接取前置条件与执行期锁定：
- 发布者不能接取自己的任务；
- 单人任务不接受 team_id，团队任务必须组队；
- 团队人数不足任务要求时拒绝；
- 执行中队伍名单锁定（邀请/退出均 409）；
- 队长不能直接退出。
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ValidationException,
)
from app.core.security import async_get_password_hash
from app.core.timezone import now_utc
from app.database import get_session
from app.models.organization import MemberProfile
from app.models.user import User
from app.repositories.task_repo import TaskRepository
from app.schemas.task import ClaimCreate, TaskCreate, TeamCreate
from app.services.task.task_service import TaskService
from app.services.task.team_service import TeamService

pytestmark = pytest.mark.integration


async def _make_user(db, sfx: str, tag: str) -> User:
    user = User(
        username=f"life_{tag}_{sfx}",
        email=f"life_{tag}_{sfx}@t.com",
        hashed_password=await async_get_password_hash("StrongPass1!"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(MemberProfile(user_id=user.id, membership_status="active"))
    await db.flush()
    return user


async def _publish(db, task_id: int) -> None:
    """测试内直接把草稿置为 published，避免依赖资金托管链路。"""
    repo = TaskRepository(db)
    task = await repo.get(task_id)
    await repo.update(task, {"status": "published", "version": task.version + 1})
    await db.flush()


def _task_payload(title: str, **overrides) -> TaskCreate:
    payload = {
        "title": title,
        "description": "生命周期测试任务描述文本",
        "reward_total": "100",
        "execution_mode": "single",
        "max_members": 1,
        "deadline": now_utc() + timedelta(days=1),
        "visibility": "members",
    }
    payload.update(overrides)
    return TaskCreate(**payload)


async def test_publisher_cannot_claim_own_task():
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "pub")
        service = TaskService(db)
        task = await service.create_task(
            actor=publisher,
            data=_task_payload(f"自接任务 {sfx}"),
            idempotency_key=f"create-{sfx}",
        )
        await _publish(db, task["id"])
        with pytest.raises(AuthorizationException):
            await service.claim_task(
                actor=publisher,
                task_id=task["id"],
                data=ClaimCreate(),
                idempotency_key=f"claim-{sfx}",
            )
        await db.rollback()


async def test_single_task_rejects_team_id():
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "pub")
        captain = await _make_user(db, sfx, "cap")
        service = TaskService(db)
        team_service = TeamService(db)
        task = await service.create_task(
            actor=publisher,
            data=_task_payload(f"单人任务 {sfx}"),
            idempotency_key=f"create-{sfx}",
        )
        await _publish(db, task["id"])
        team = await team_service.create_team(
            actor=captain,
            data=TeamCreate(name=f"队 {sfx}"),
            idempotency_key=f"team-{sfx}",
        )
        with pytest.raises(ValidationException):
            await service.claim_task(
                actor=captain,
                task_id=task["id"],
                data=ClaimCreate(team_id=team["id"]),
                idempotency_key=f"claim-{sfx}",
            )
        await db.rollback()


async def test_team_task_requires_team():
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "pub")
        worker = await _make_user(db, sfx, "worker")
        service = TaskService(db)
        task = await service.create_task(
            actor=publisher,
            data=_task_payload(
                f"团队任务 {sfx}",
                execution_mode="team",
                max_members=3,
            ),
            idempotency_key=f"create-{sfx}",
        )
        await _publish(db, task["id"])
        with pytest.raises(ValidationException):
            await service.claim_task(
                actor=worker,
                task_id=task["id"],
                data=ClaimCreate(),
                idempotency_key=f"claim-{sfx}",
            )
        await db.rollback()


async def test_team_with_only_captain_rejected():
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "pub")
        captain = await _make_user(db, sfx, "cap")
        service = TaskService(db)
        team_service = TeamService(db)
        task = await service.create_task(
            actor=publisher,
            data=_task_payload(
                f"团队人数任务 {sfx}", execution_mode="team", max_members=3
            ),
            idempotency_key=f"create-{sfx}",
        )
        await _publish(db, task["id"])
        team = await team_service.create_team(
            actor=captain,
            data=TeamCreate(name=f"独队 {sfx}"),
            idempotency_key=f"team-{sfx}",
        )
        with pytest.raises(ValidationException):
            await service.claim_task(
                actor=captain,
                task_id=task["id"],
                data=ClaimCreate(team_id=team["id"]),
                idempotency_key=f"claim-{sfx}",
            )
        await db.rollback()


async def test_roster_locked_after_claim_and_captain_cannot_leave():
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        publisher = await _make_user(db, sfx, "pub")
        captain = await _make_user(db, sfx, "cap")
        worker = await _make_user(db, sfx, "worker")
        extra = await _make_user(db, sfx, "extra")
        service = TaskService(db)
        team_service = TeamService(db)
        task = await service.create_task(
            actor=publisher,
            data=_task_payload(
                f"锁定任务 {sfx}", execution_mode="team", max_members=3
            ),
            idempotency_key=f"create-{sfx}",
        )
        await _publish(db, task["id"])

        team = await team_service.create_team(
            actor=captain,
            data=TeamCreate(name=f"锁定队 {sfx}", invitee_user_ids=[worker.id]),
            idempotency_key=f"team-{sfx}",
        )
        invitations, _ = await team_service.list_pending_invitations(actor=worker)
        await team_service.respond_invitation(
            actor=worker,
            invitation_id=invitations[0].id,
            accept=True,
            idempotency_key=f"join-{sfx}",
        )

        claim = await service.claim_task(
            actor=captain,
            task_id=task["id"],
            data=ClaimCreate(team_id=team["id"]),
            idempotency_key=f"claim-{sfx}",
        )
        assert len(claim["members"]) == 2

        with pytest.raises(ConflictException):
            await team_service.invite(
                actor=captain,
                team_id=team["id"],
                data=__import__(
                    "app.schemas.task", fromlist=["InvitationCreate"]
                ).InvitationCreate(invitee_user_id=extra.id),
                idempotency_key=f"invite-{sfx}",
            )
        with pytest.raises(ConflictException):
            await team_service.leave_team(
                actor=worker,
                team_id=team["id"],
                idempotency_key=f"leave-{sfx}",
            )
        with pytest.raises(ConflictException):
            await team_service.leave_team(
                actor=captain,
                team_id=team["id"],
                idempotency_key=f"leave-cap-{sfx}",
            )

        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await db.rollback()
