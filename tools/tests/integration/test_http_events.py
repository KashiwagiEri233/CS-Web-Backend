"""活动路由 HTTP → 鉴权 → Service → Repository → PostgreSQL 完整链路。

补 ER-11 盲区：events 路由此前无真实 DB 的 HTTP 级测试
（test_phase3_events 走 service 层、test_repositories_events 走 repo 层）。
覆盖：活动列表（status/tag 过滤，tag 为 event_repo.py:36 修复的 HTTP 回归）、
详情、报名 / 重复报名 409 / 取消 / 报名状态（未报名 404、已报名 200、取消后
cancelled）、我的报名列表、不存在活动 404。

本地无法连接数据库时自动 skip；CI 严格模式下直接失败。
"""

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.security import async_get_password_hash
from app.database import get_session
from app.main import create_app
from app.models.event import Event
from app.models.user import User

pytestmark = pytest.mark.integration

_PASSWORD = "StrongPass1!"


async def _make_user(db, sfx: str) -> int:
    user = User(
        username=f"itest_http_evt_{sfx}",
        email=f"itest_http_evt_{sfx}@t.com",
        hashed_password=await async_get_password_hash(_PASSWORD),
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user.id


async def _cleanup(db, user_ids: list[int], event_ids: list[int]) -> None:
    """先删报名/签到（event_id），再删鉴权侧挂靠行（user_id），
    最后删活动与用户（events.created_by 为 NO ACTION，须显式删）。"""
    for table in ("event_checkins", "event_registrations"):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE event_id = ANY(:ids)"),
                    {"ids": event_ids},
                )
        except Exception:
            pass
    for table in (
        "refresh_tokens",
        "login_history",
        "password_history",
        "notifications",
        "two_factor_auth",
        "verification_codes",
        "password_reset_requests",
        "user_roles",
    ):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                    {"ids": user_ids},
                )
        except Exception:
            pass
    await db.execute(
        text("DELETE FROM events WHERE id = ANY(:ids)"), {"ids": event_ids}
    )
    await db.execute(
        text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids}
    )
    await db.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login-json",
        json={"username": username, "password": _PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


async def test_events_http_user_flow(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        organizer_id = await _make_user(db, f"{sfx}org")
        user_id = await _make_user(db, f"{sfx}usr")
        event = Event(
            title=f"http-活动-{sfx}",
            description="desc",
            status="upcoming",
            date="2099.12.31",
            tags=["python"],
            capacity=0,
            created_by=organizer_id,
        )
        db.add(event)
        await db.commit()
        event_id = event.id

    application = create_app()
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            h_user = await _login(client, f"itest_http_evt_{sfx}usr")

            # 公开列表（匿名）+ status 过滤
            lst = await client.get("/api/v1/events", params={"status": "upcoming"})
            assert lst.status_code == 200, lst.text
            assert any(e["id"] == event_id for e in lst.json()["items"])

            # tag 过滤（event_repo.py:36 修复的 HTTP 回归：不再 500 且命中）
            tag_lst = await client.get("/api/v1/events", params={"tag": "python"})
            assert tag_lst.status_code == 200, tag_lst.text
            assert any(e["id"] == event_id for e in tag_lst.json()["items"])

            # 详情
            detail = await client.get(f"/api/v1/events/{event_id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["title"] == f"http-活动-{sfx}"

            # 未报名时查询报名状态 -> 404
            not_reg = await client.get(
                f"/api/v1/events/{event_id}/registration", headers=h_user
            )
            assert not_reg.status_code == 404

            # 报名
            reg = await client.post(
                f"/api/v1/events/{event_id}/register",
                headers=h_user,
                json={"form_data": {"qq": "123"}},
            )
            assert reg.status_code == 200, reg.text
            assert reg.json()["status"] == "registered"

            # 报名状态 -> 200
            reg_status = await client.get(
                f"/api/v1/events/{event_id}/registration", headers=h_user
            )
            assert reg_status.status_code == 200, reg_status.text
            assert reg_status.json()["status"] == "registered"

            # 我的报名列表
            mine = await client.get("/api/v1/events/me/registered", headers=h_user)
            assert mine.status_code == 200, mine.text
            assert any(e["id"] == event_id for e in mine.json())

            # 重复报名 -> 409
            dup = await client.post(
                f"/api/v1/events/{event_id}/register", headers=h_user, json={}
            )
            assert dup.status_code == 409, dup.text

            # 取消报名 -> 状态转 cancelled
            cancel = await client.delete(
                f"/api/v1/events/{event_id}/register", headers=h_user
            )
            assert cancel.status_code == 200, cancel.text
            reg_after = await client.get(
                f"/api/v1/events/{event_id}/registration", headers=h_user
            )
            assert reg_after.status_code == 200
            assert reg_after.json()["status"] == "cancelled"

            # 不存在的活动 -> 404
            missing = await client.get("/api/v1/events/999999")
            assert missing.status_code == 404
    finally:
        async with get_session() as db:
            await _cleanup(db, [organizer_id, user_id], [event_id])
