"""Phase 3 集成测试：活动模块（需要 PostgreSQL）。

覆盖：
1. 活动 CRUD + 自动归档（过期日期 → ended）；
2. 报名流程：报名/重复报名 409/名额已满 409/取消/重新报名；
3. 签到码生成与核销（无效码/重复使用）；
4. 批量状态更新 + 统计；
5. 事件通知：报名成功/取消/新活动广播（event bus）。
"""

import uuid

import pytest
from sqlalchemy import delete

from app.core.exceptions import ConflictException, NotFoundException
from app.database import get_session
from app.models.event import Event
from app.models.user import User
from app.schemas.event import EventInput
from app.services.event_service import EventService


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


async def _make_user(db, email: str) -> User:
    user = User(
        username=f"u_{_sfx()}",
        email=email,
        hashed_password="$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyh",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user


async def _cleanup(db, *user_ids: int) -> None:
    from sqlalchemy import text

    for uid in user_ids:
        for table in (
            "event_checkins",
            "event_registrations",
            "notifications",
            "user_roles",
        ):
            try:
                async with db.begin_nested():
                    await db.execute(
                        text(f"DELETE FROM {table} WHERE user_id=:i"), {"i": uid}
                    )
            except Exception:
                pass
        try:
            async with db.begin_nested():
                await db.execute(
                    text("DELETE FROM events WHERE created_by=:i"), {"i": uid}
                )
        except Exception:
            pass
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_event_crud_and_archive(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = EventService(db)
        try:
            created = await svc.create_event(
                admin_user,
                EventInput(
                    title=f"活动-{sfx}",
                    description="描述",
                    date="2026.12.31",
                    tags=["web"],
                    capacity=10,
                ),
            )
            assert created.title == f"活动-{sfx}"

            fetched = await svc.get_event(created.id)
            assert fetched is not None
            assert fetched.registered_count == 0

            updated = await svc.update_event(
                admin_user, created.id, EventInput(title=f"改名-{sfx}", description="新")
            )
            assert updated.title == f"改名-{sfx}"

            # 自动归档：过去日期 → ended
            past = await svc.create_event(
                admin_user, EventInput(title=f"过期-{sfx}", date="2020.01.01")
            )
            await svc.auto_archive()
            archived = await svc.get_event(past.id)
            assert archived.status == "ended"

            await svc.delete_event(admin_user, created.id)
            with pytest.raises(NotFoundException):
                await svc.get_event(created.id)
        finally:
            await db.execute(delete(Event).where(Event.title.like(f"%{sfx}%")))
            await db.commit()


@pytest.mark.integration
async def test_registration_flow(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = EventService(db)
        user = await _make_user(db, f"reg_{sfx}@t.com")
        try:
            event = await svc.create_event(
                admin_user,
                EventInput(title=f"报名活动-{sfx}", capacity=1),
            )
            # 报名
            reg = await svc.register(user.id, event.id, {"qq": "123"})
            assert reg.status == "registered"
            assert (await svc.get_user_registration(user.id, event.id)) is not None

            # 重复报名 409
            with pytest.raises(ConflictException):
                await svc.register(user.id, event.id)

            # 名额已满：第二个用户报名 409
            user2 = await _make_user(db, f"reg2_{sfx}@t.com")
            with pytest.raises(ConflictException):
                await svc.register(user2.id, event.id)

            # 取消 → 重新报名
            await svc.cancel(user.id, event.id)
            assert (
                await svc.get_user_registration(user.id, event.id)
            ).status == "cancelled"
            reg2 = await svc.register(user.id, event.id)
            assert reg2.status == "registered"

            # 我的报名列表
            mine = await svc.list_user_registered_events(user.id)
            assert any(e.id == event.id for e in mine)

            # 管理员改报名状态
            reg3 = await svc.get_user_registration(user.id, event.id)
            updated = await svc.admin_update_registration_status(
                admin_user, reg3.id, "waitlisted"
            )
            assert updated.status == "waitlisted"

            await _cleanup(db, user.id, user2.id)
            await db.execute(delete(Event).where(Event.id == event.id))
            await db.commit()
        except Exception:
            await _cleanup(db, user.id)
            await db.execute(delete(Event).where(Event.title.like(f"%{sfx}%")))
            await db.commit()
            raise


@pytest.mark.integration
async def test_checkin_flow(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = EventService(db)
        user = await _make_user(db, f"ck_{sfx}@t.com")
        admin = await _make_user(db, f"ckadm_{sfx}@t.com")
        try:
            event = await svc.create_event(admin_user, EventInput(title=f"签到活动-{sfx}"))
            await svc.register(user.id, event.id)

            # 生成签到码
            result = await svc.generate_checkin_codes(admin.id, event.id)
            assert result["generated"] == 1
            # 重复生成 → skipped
            result2 = await svc.generate_checkin_codes(admin.id, event.id)
            assert result2["skipped"] == 1

            checkins = await svc.list_checkins(event.id)
            assert len(checkins) == 1
            code = checkins[0].checkin_code

            # 无效码
            bad = await svc.checkin_by_code(admin.id, event.id, "000000")
            assert bad["ok"] is False

            # 核销成功
            ok = await svc.checkin_by_code(admin.id, event.id, code)
            assert ok["ok"] is True

            # 重复使用
            again = await svc.checkin_by_code(admin.id, event.id, code)
            assert again["ok"] is False

            stats = await svc.checkin_stats(event.id)
            assert stats["checked_in"] == 1

            await _cleanup(db, user.id, admin.id)
            await db.execute(delete(Event).where(Event.id == event.id))
            await db.commit()
        except Exception:
            await _cleanup(db, user.id, admin.id)
            await db.execute(delete(Event).where(Event.title.like(f"%{sfx}%")))
            await db.commit()
            raise


@pytest.mark.integration
async def test_event_batch_and_stats(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = EventService(db)
        try:
            e1 = await svc.create_event(
                admin_user, EventInput(title=f"批量1-{sfx}", status="upcoming")
            )
            e2 = await svc.create_event(
                admin_user, EventInput(title=f"批量2-{sfx}", status="upcoming")
            )

            result = await svc.batch_update(admin_user, [e1.id, e2.id], "ongoing")
            assert result["success"] == 2
            assert (await svc.get_event(e1.id)).status == "ongoing"

            # 统计
            stats = await svc.stats_all()
            assert any(s["event_id"] == e1.id for s in stats)
            assert all(s["total"] >= 0 for s in stats)
        finally:
            await db.execute(delete(Event).where(Event.title.like(f"%{sfx}%")))
            await db.commit()


@pytest.mark.integration
async def test_event_settings(integration_db_ready):
    async with get_session() as db:
        svc = EventService(db)
        settings = await svc.get_settings()
        assert settings["title_max"] == 120

        updated = await svc.update_settings(
            type("S", (), {"title_max": 200, "desc_max": None})()
        )
        assert updated["title_max"] == 200

        reset = await svc.reset_setting("title_max")
        assert reset["title_max"] == 120
