"""组织/成员历史（P7 补齐）：审计条目可查 + 峰范围拒绝跨峰历史。"""

import types
import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import AuthorizationException
from app.database import get_session
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.organization.organization_service import OrganizationService

pytestmark = pytest.mark.integration


async def test_member_history_from_audit_logs(admin_user):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        org = OrganizationService(db)
        actor = (
            await db.execute(select(User).where(User.id == admin_user))
        ).scalar_one()
        peak = await org.create_peak({"code": f"ph{sfx}", "name": "历史峰"})
        member_user = User(
            username=f"history_{sfx}",
            email=f"history_{sfx}@t.com",
            hashed_password="$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyh",
            is_active=True,
        )
        db.add(member_user)
        await db.flush()
        member = await org.create_member(
            actor, user_id=member_user.id, peak_id=peak.id, student_id=None
        )

        audit = AuditService(db)
        await audit.record_atomic(
            action="organization.member.create",
            resource_type="member",
            resource_id=str(member["id"]),
            actor_id=actor.id,
            actor_username=actor.username,
            detail={"user_id": member_user.id, "peak_id": peak.id},
        )

        rows, total = await audit.list_logs(
            resource_type="member", resource_id=str(member["id"])
        )
        assert total >= 1
        assert rows[0].action == "organization.member.create"

        # 超级管理员具备全范围，可读跨峰组织历史
        await org.require_global_scope(actor)

        await db.rollback()


async def test_require_global_scope_rejects_peak_scope():
    """峰范围账号不能读取跨峰组织历史。"""
    service = OrganizationService(None)  # type: ignore[arg-type]

    async def _fake_scopes(user_id: int):
        return [{"scope_type": "peak", "scope_peak_id": 9}]

    service.repo.get_role_scopes = _fake_scopes  # type: ignore[method-assign]
    actor = types.SimpleNamespace(id=7, is_superuser=False)

    with pytest.raises(AuthorizationException):
        await service.require_global_scope(actor)
