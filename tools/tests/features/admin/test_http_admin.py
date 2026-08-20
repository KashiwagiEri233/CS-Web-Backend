"""管理员 RBAC 路由 HTTP → 鉴权 → Service → Repository → PostgreSQL 完整链路。

补 ER-11 最后盲区：admin_users / admin_roles / admin_events / admin_community 四个
管理域路由此前无真实 DB 的 HTTP 级测试（仅有 RBAC 服务层 test_rbac_db 与
社区/活动/工具域 HTTP 测试）。本文件覆盖：
- 权限接线：无权限普通用户 → 403（PermissionDenied）；授该权限的普通用户 → 200；
- 管理员强制 2FA 门禁：superuser 未启用 2FA → 422（TWO_FACTOR_NOT_SETUP）；
- superuser 绕过分支：superuser 启用 2FA → 200（同时证明 require_admin_2fa 放行）。
- 同源缺陷回归：``workbench /stats/api-usage`` 此前因 ``require_admin_2fa`` 工厂
  未调用而完全裸奔（无鉴权即可访问），修复后未带 token→401、superuser 无 2FA→422、
  启用→200。

设计要点（已勘察确认）：
- 4 个 admin 模块顶层均挂 Depends(require_admin_2fa)；路由再各自挂
  require_permission(资源, 动作)。superuser 绕过权限但受 2FA 门禁约束；
  非管理员普通用户走 require_admin_2fa 短路、仅按权限集判定。
- PermissionDeniedException -> 403；ValidationException(TWO_FACTOR_NOT_SETUP) -> 422。
- login-json 走 auth_service.login(username)，不检查 2FA（仅 login_by_email 才走
  2FA 预认证），故启用 2FA 的 superuser 仍可正常登录拿 token。

本地无法连接数据库时自动 skip；CI 严格模式下直接失败。
"""

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.security import async_get_password_hash
from app.core.timezone import now_utc
from app.core.totp import generate_code
from app.database import get_session
from app.main import create_app
from app.models.user import User
from app.repositories.rbac_repo import RBACRepository
from app.services.rbac_service import RBACService
from app.services.totp_service import TOTPService

pytestmark = pytest.mark.integration

_PASSWORD = "StrongPass1!"

# 4 个 admin 域各取 1 个读路由（权限依赖同构，读路由零业务副作用、清理简单）
_ADMIN_READ_ROUTES = [
    ("/api/v1/admin/users", "user:list"),
    ("/api/v1/admin/roles", "role:list"),
    ("/api/v1/admin/permissions", "permission:list"),
    ("/api/v1/admin/events", "event:read"),
    ("/api/v1/admin/community/topics", "community:read"),
]


async def _make_user(db, sfx: str, *, is_superuser: bool = False) -> int:
    user = User(
        username=f"itest_http_admin_{sfx}",
        email=f"itest_http_admin_{sfx}@t.com",
        hashed_password=await async_get_password_hash(_PASSWORD),
        is_active=True,
        is_superuser=is_superuser,
    )
    db.add(user)
    await db.commit()
    return user.id


async def _grant(db, user_id: int, perms: list[str]) -> tuple[int, list[int]]:
    """建一个角色，挂 perms（["resource:action", ...]），赋给用户。返回 (role_id, perm_ids)。"""
    repo = RBACRepository(db)
    svc = RBACService(db)
    role = await repo.create_role(
        {"name": f"itest_http_admin_r_{user_id}", "description": "i", "is_active": True}
    )
    perm_ids: list[int] = []
    for p in perms:
        resource, action = p.split(":", 1)
        perm = await repo.create_permission(
            {"name": p, "resource": resource, "action": action, "description": "i"}
        )
        perm_ids.append(perm.id)
    await svc.grant_role_to_user(user_id, role.id)
    for pid in perm_ids:
        await svc.grant_permission_to_role(role.id, pid)
    await db.commit()
    return role.id, perm_ids


async def _enable_2fa(db, user_id: int) -> None:
    """在测试中完整启用 2FA：setup 取 secret -> 生成当前时刻 TOTP 码 -> confirm 激活。"""
    totp = TOTPService(db)
    res = await totp.setup(user_id, "t@t.com")
    secret = res["secret"]
    code = generate_code(
        secret, int(now_utc().timestamp()), period=settings.TOTP_STEP_SECONDS
    )
    await totp.confirm(user_id, code)


async def _cleanup(
    db,
    user_ids: list[int],
    role_ids: list[int] | None = None,
    perm_ids: list[int] | None = None,
) -> None:
    """按 FK 依赖序清场：先鉴权/审计/角色挂靠行，再角色-权限关联与角色/权限主表，最后用户。"""
    for table in (
        "user_roles",
        "refresh_tokens",
        "login_history",
        "password_history",
        "two_factor_auth",
        "verification_codes",
        "password_reset_requests",
        "notifications",
        "audit_logs",
    ):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                    {"ids": user_ids},
                )
        except Exception:
            pass
    if role_ids:
        try:
            async with db.begin_nested():
                await db.execute(
                    text("DELETE FROM role_permissions WHERE role_id = ANY(:ids)"),
                    {"ids": role_ids},
                )
        except Exception:
            pass
    if role_ids:
        await db.execute(
            text("DELETE FROM roles WHERE id = ANY(:ids)"), {"ids": role_ids}
        )
    if perm_ids:
        await db.execute(
            text("DELETE FROM permissions WHERE id = ANY(:ids)"), {"ids": perm_ids}
        )
    await db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})
    await db.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login-json",
        json={"username": username, "password": _PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


async def test_admin_routes_forbidden_without_permission(integration_db_ready):
    """无权限普通用户访问任意 admin 读路由 -> 403（PermissionDenied）。"""
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, f"{sfx}noperm")

    application = create_app()
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            h = await _login(client, f"itest_http_admin_{sfx}noperm")
            for route, _perm in _ADMIN_READ_ROUTES:
                r = await client.get(route, headers=h)
                assert r.status_code == 403, f"{route} -> {r.status_code}: {r.text}"
    finally:
        async with get_session() as db:
            await _cleanup(db, [uid])


async def test_admin_routes_allowed_with_permissions(integration_db_ready):
    """被授予对应权限的普通用户访问各 admin 读路由 -> 200（权限接线端到端）。"""
    sfx = uuid.uuid4().hex[:8]
    perms = [perm for _route, perm in _ADMIN_READ_ROUTES]
    async with get_session() as db:
        uid = await _make_user(db, f"{sfx}perm")
        role_id, perm_ids = await _grant(db, uid, perms)

    application = create_app()
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            h = await _login(client, f"itest_http_admin_{sfx}perm")
            for route, _perm in _ADMIN_READ_ROUTES:
                r = await client.get(route, headers=h)
                assert r.status_code == 200, f"{route} -> {r.status_code}: {r.text}"
    finally:
        async with get_session() as db:
            await _cleanup(db, [uid], [role_id], perm_ids)


async def test_admin_2fa_gate_superuser_without_2fa(integration_db_ready):
    """管理员强制 2FA：superuser 未启用 2FA 访问 admin 路由 -> 422（TWO_FACTOR_NOT_SETUP）。"""
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, f"{sfx}su", is_superuser=True)

    application = create_app()
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            h = await _login(client, f"itest_http_admin_{sfx}su")
            r = await client.get("/api/v1/admin/users", headers=h)
            assert r.status_code == 422, r.text
            # 锁 error_code 语义：门禁确实因 2FA 未启用触发
            assert "TWO_FACTOR_NOT_SETUP" in r.text, r.text
    finally:
        async with get_session() as db:
            await _cleanup(db, [uid])


async def test_admin_2fa_gate_superuser_with_2fa_bypass(integration_db_ready):
    """superuser 启用 2FA 后访问 admin 路由 -> 200（2FA 门禁放行 + superuser 绕过权限）。"""
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, f"{sfx}su2", is_superuser=True)
        await _enable_2fa(db, uid)

    application = create_app()
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            h = await _login(client, f"itest_http_admin_{sfx}su2")
            r = await client.get("/api/v1/admin/users", headers=h)
            assert r.status_code == 200, r.text
    finally:
        async with get_session() as db:
            await _cleanup(db, [uid])


async def test_workbench_api_usage_2fa_gate(integration_db_ready):
    """同源安全缺陷回归：workbench /stats/api-usage 此前因 ``require_admin_2fa``
    工厂未调用（Depends(require_admin_2fa) 而非 Depends(require_admin_2fa())）而
    完全裸奔——无任何鉴权即可访问（API 用量统计数据泄露）。

    修复后该端点：
    - 未带 token -> 401（鉴权依赖现在真正解析 current_user，此前为 200 裸奔）
    - superuser 未启用 2FA -> 422（2FA 门禁真正执行）
    - superuser 启用 2FA -> 200（门禁放行）
    """
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid_no2fa = await _make_user(db, f"{sfx}wb1", is_superuser=True)
        uid_2fa = await _make_user(db, f"{sfx}wb2", is_superuser=True)
        await _enable_2fa(db, uid_2fa)

    application = create_app()
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            # 1) 未鉴权 -> 401（修复前裸奔返回 200）
            r0 = await client.get("/api/v1/workbench/stats/api-usage")
            assert r0.status_code == 401, r0.text

            # 2) superuser 未启用 2FA -> 422（2FA 门禁现在真正执行）
            h_no = await _login(client, f"itest_http_admin_{sfx}wb1")
            r1 = await client.get("/api/v1/workbench/stats/api-usage", headers=h_no)
            assert r1.status_code == 422, r1.text
            assert "TWO_FACTOR_NOT_SETUP" in r1.text, r1.text

            # 3) superuser 启用 2FA -> 200（门禁放行）
            h_yes = await _login(client, f"itest_http_admin_{sfx}wb2")
            r2 = await client.get("/api/v1/workbench/stats/api-usage", headers=h_yes)
            assert r2.status_code == 200, r2.text
    finally:
        async with get_session() as db:
            await _cleanup(db, [uid_no2fa, uid_2fa])
