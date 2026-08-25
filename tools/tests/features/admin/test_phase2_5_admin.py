"""子阶段 2.5 集成测试：管理员角色/权限管理 + 审计日志删除（需要 PostgreSQL）。

覆盖：
1. 角色列表（权限名 + 用户数 + is_system 标记）；
2. 创建角色（含权限自动创建）→ 更新 → 全量替换权限 → 删除；
3. 系统内置角色禁止删除；
4. 审计日志删除（单条 + 批量 before）。
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import ConflictException
from app.database import get_session
from app.models.role import Role
from app.schemas.rbac import AdminRoleCreate, AdminRoleUpdate
from app.services.audit_service import AuditService
from app.services.rbac.rbac_service import RBACService


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


async def _cleanup_role(db, name: str) -> None:
    from sqlalchemy import text

    role = (
        await db.execute(select(Role).where(Role.name == name))
    ).scalar_one_or_none()
    if role is not None:
        await db.execute(
            text("DELETE FROM user_roles WHERE role_id=:r"), {"r": role.id}
        )
        await db.execute(
            text("DELETE FROM role_permissions WHERE role_id=:r"), {"r": role.id}
        )
        await db.delete(role)
        await db.commit()


@pytest.mark.integration
async def test_role_admin_crud_flow(integration_db_ready):
    role_key = f"custom_{_sfx()}"
    async with get_session() as db:
        svc = RBACService(db)
        try:
            # 创建（权限名不存在时自动创建）
            role = await svc.create_role_admin(
                AdminRoleCreate(
                    name=role_key,
                    display_name="自定义角色",
                    description="测试",
                    permissions=["community_topic:hide", "event:create"],
                )
            )
            assert role.display_name == "自定义角色"
            assert role.is_system is False

            # 列表含权限名与用户数
            listed = await svc.list_roles_admin()
            item = next(r for r in listed if r["name"] == role_key)
            assert set(item["permissions"]) == {"community_topic:hide", "event:create"}
            assert item["user_count"] == 0
            assert item["is_system"] is False

            # 更新元数据
            await svc.update_role_admin(role.id, AdminRoleUpdate(display_name="新名字"))
            refreshed = next(
                r for r in await svc.list_roles_admin() if r["id"] == role.id
            )
            assert refreshed["display_name"] == "新名字"

            # 全量替换权限
            await svc.replace_role_permissions(
                role.id, ["event:delete", "event:create"]
            )
            after = next(r for r in await svc.list_roles_admin() if r["id"] == role.id)
            assert set(after["permissions"]) == {"event:delete", "event:create"}

            # 删除
            assert await svc.delete_role_admin(role.id) is True
            assert all(r["id"] != role.id for r in await svc.list_roles_admin())
        finally:
            await _cleanup_role(db, role_key)


@pytest.mark.integration
async def test_system_role_delete_protected(integration_db_ready):
    async with get_session() as db:
        svc = RBACService(db)
        system_role = (
            await db.execute(select(Role).where(Role.name == "user"))
        ).scalar_one_or_none()
        if system_role is None or not system_role.is_system:
            pytest.skip("缺少系统内置 user 角色")
        with pytest.raises(ConflictException):
            await svc.delete_role_admin(system_role.id)


@pytest.mark.integration
async def test_audit_log_delete_flow(integration_db_ready):
    async with get_session() as db:
        svc = AuditService(db)
        # 写入两条测试日志
        await svc.record(
            action="test.phase2_5",
            resource_type="test",
            detail={"marker": _sfx()},
        )
        await svc.record(
            action="test.phase2_5",
            resource_type="test",
            detail={"marker": _sfx()},
        )
        logs, _total = await svc.list_logs(action="test.phase2_5", limit=10)
        assert len(logs) >= 2

        first_id = logs[0].id
        assert await svc.delete_log(first_id) is True
        assert await svc.get_log(first_id) is None

        from app.core.timezone import now_utc

        count = await svc.delete_logs_before(now_utc())
        assert count >= 1
        remaining, _total2 = await svc.list_logs(action="test.phase2_5", limit=10)
        assert all(r.id != first_id for r in remaining)
