"""完整 HTTP → 鉴权 → Service → Repository → PostgreSQL 链路。"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.security import async_get_password_hash
from app.database import get_session
from app.main import create_app
from app.models.user import User

pytestmark = pytest.mark.integration

_PASSWORD = "StrongPass1!"


async def test_http_auth_user_and_revocation_flow(integration_db_ready):
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"e2e_admin_{suffix}"
    user_name = f"e2e_user_{suffix}"
    admin_id: int | None = None
    user_id: int | None = None

    async with get_session() as db:
        admin = User(
            username=admin_name,
            email=f"{admin_name}@example.com",
            hashed_password=await async_get_password_hash(_PASSWORD),
            is_active=True,
            is_superuser=True,
        )
        db.add(admin)
        await db.commit()
        admin_id = admin.id

    application = create_app()
    try:
        async with httpx.AsyncClient(
            app=application, base_url="http://testserver"
        ) as client:
            admin_login = await client.post(
                "/api/v1/auth/login-json",
                json={"username": admin_name, "password": _PASSWORD},
            )
            assert admin_login.status_code == 200, admin_login.text
            admin_token = admin_login.json()["access_token"]

            created = await client.post(
                "/api/v1/auth/register",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "username": user_name,
                    "email": f"{user_name}@example.com",
                    "password": _PASSWORD,
                    "full_name": "Integration User",
                },
            )
            assert created.status_code == 200, created.text
            user_id = created.json()["id"]

            login = await client.post(
                "/api/v1/auth/login-json",
                json={"username": user_name, "password": _PASSWORD},
            )
            assert login.status_code == 200, login.text
            token_pair = login.json()
            user_headers = {"Authorization": f"Bearer {token_pair['access_token']}"}

            profile = await client.get("/api/v1/auth/me", headers=user_headers)
            assert profile.status_code == 200
            assert profile.json()["username"] == user_name

            updated = await client.put(
                "/api/v1/users/me",
                headers=user_headers,
                json={"full_name": "Updated Through HTTP"},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["full_name"] == "Updated Through HTTP"

            logout = await client.post(
                "/api/v1/auth/logout",
                headers=user_headers,
                json={"refresh_token": token_pair["refresh_token"]},
            )
            assert logout.status_code == 200, logout.text

            revoked = await client.get("/api/v1/auth/me", headers=user_headers)
            assert revoked.status_code == 401
    finally:
        ids = [value for value in (admin_id, user_id) if value is not None]
        if ids:
            async with get_session() as db:
                await db.execute(
                    text("DELETE FROM refresh_tokens WHERE user_id = ANY(:ids)"),
                    {"ids": ids},
                )
                await db.execute(
                    text("DELETE FROM user_roles WHERE user_id = ANY(:ids)"),
                    {"ids": ids},
                )
                await db.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": ids},
                )
                await db.commit()
