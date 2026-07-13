"""RBAC 服务层数据库集成测试（需要可用的 PostgreSQL）。

锁定 2026-06-16 端到端测试发现的回归点：
1. grant_role_to_user 曾用 get_user_by_id（未预加载 roles）-> 访问 user.roles 触发异步懒加载 500；
2. get_user_with_roles 未嵌套预加载 role.permissions -> 用户有角色后聚合权限 500。

本地无法连接数据库时自动 skip；CI 严格模式下直接失败。
"""

import uuid

from sqlalchemy import text

from app.database import get_session
from app.models.user import User
from app.services.rbac_service import RBACService
from app.repositories.rbac_repo import RBACRepository


async def test_grant_role_then_aggregate_permissions(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    uname, rname, pname = f"itest_u_{sfx}", f"itest_r_{sfx}", f"itest:p_{sfx}"

    async with get_session() as db:
        repo = RBACRepository(db)
        svc = RBACService(db)

        # 准备：建用户 / 角色 / 权限
        user = User(
            username=uname,
            email=f"{uname}@t.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
        )
        db.add(user)
        await db.flush()
        role = await repo.create_role(
            {"name": rname, "description": "i", "is_active": True}
        )
        perm = await repo.create_permission(
            {
                "name": pname,
                "resource": "itest",
                "action": f"p_{sfx}",
                "description": "i",
            }
        )
        await db.commit()
        uid = user.id

        try:
            # 1) 赋角色不应 500（曾因懒加载 user.roles 崩）
            assert await svc.grant_role_to_user(uid, role.id) is True
            # 2) 角色赋权
            assert await svc.grant_permission_to_role(role.id, perm.id) is True
            # 3) 聚合权限不应 500（曾因未预加载 role.permissions 崩），且包含刚赋的权限
            perms = await svc.get_user_permissions(uid)
            assert f"itest:p_{sfx}" in perms
            # 4) check_permission 一致
            assert await svc.check_permission(uid, "itest", f"p_{sfx}") is True
            assert await svc.check_permission(uid, "itest", "nope") is False
        finally:
            # 清理（先关联表后主表）
            async with get_session() as db2:
                await db2.execute(
                    text("DELETE FROM user_roles WHERE user_id=:i"), {"i": uid}
                )
                await db2.execute(
                    text("DELETE FROM role_permissions WHERE role_id=:r"),
                    {"r": role.id},
                )
                await db2.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
                await db2.execute(text("DELETE FROM roles WHERE id=:r"), {"r": role.id})
                await db2.execute(
                    text("DELETE FROM permissions WHERE id=:p"), {"p": perm.id}
                )
                await db2.commit()
