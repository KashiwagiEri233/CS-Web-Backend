"""公告/活动可见范围集成测试（P4）。

直接写入模型并查询服务，全部在事务内回滚，不留下公告/活动/成员数据。
"""

import uuid

import pytest

from app.core.timezone import now_utc
from app.database import get_session
from app.models.event import Event
from app.models.notification import Announcement
from app.models.organization import MemberProfile, Peak
from app.models.user import User
from app.services.announcement_service import AnnouncementService
from app.services.event.event_service import EventService

pytestmark = pytest.mark.integration


async def _make_user(db, sfx: str, tag: str) -> User:
    user = User(
        username=f"scope_{tag}_{sfx}",
        email=f"scope_{tag}_{sfx}@t.com",
        hashed_password="$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyh",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def test_announcement_and_event_visibility(admin_user):
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        outsider = await _make_user(db, sfx, "out")
        member = await _make_user(db, sfx, "member")
        other_member = await _make_user(db, sfx, "other")
        peak_a = Peak(code=f"pa{sfx}", name="峰A")
        peak_b = Peak(code=f"pb{sfx}", name="峰B")
        db.add_all([peak_a, peak_b])
        await db.flush()
        db.add_all(
            [
                MemberProfile(user_id=member.id, peak_id=peak_a.id, membership_status="active"),
                MemberProfile(
                    user_id=other_member.id,
                    peak_id=peak_b.id,
                    membership_status="active",
                ),
            ]
        )
        await db.flush()

        db.add_all(
            [
                Announcement(
                    title="公开公告",
                    content="公开内容",
                    status="published",
                    visibility="public",
                    is_active=True,
                    created_by=admin_user,
                    published_at=now_utc(),
                ),
                Announcement(
                    title="成员公告",
                    content="成员内容",
                    status="published",
                    visibility="members",
                    is_active=True,
                    created_by=admin_user,
                    published_at=now_utc(),
                ),
                Announcement(
                    title="峰A公告",
                    content="峰A内容",
                    status="published",
                    visibility="peak",
                    peak_id=peak_a.id,
                    is_active=True,
                    created_by=admin_user,
                    published_at=now_utc(),
                ),
                Announcement(
                    title="草稿公告",
                    content="草稿内容",
                    status="draft",
                    visibility="public",
                    is_active=False,
                    created_by=admin_user,
                ),
            ]
        )
        await db.flush()

        service = AnnouncementService(db)
        outsider_titles = {a.title for a in await service.list_active(user=outsider)}
        assert "公开公告" in outsider_titles
        assert "成员公告" not in outsider_titles
        assert "峰A公告" not in outsider_titles
        assert "草稿公告" not in outsider_titles

        member_titles = {a.title for a in await service.list_active(user=member)}
        assert {"公开公告", "成员公告", "峰A公告"} <= member_titles
        other_titles = {
            a.title for a in await service.list_active(user=other_member)
        }
        assert "峰A公告" not in other_titles

        db.add_all(
            [
                Event(
                    title="公开活动",
                    status="upcoming",
                    visibility="public",
                    created_by=admin_user,
                ),
                Event(
                    title="成员活动",
                    status="upcoming",
                    visibility="members",
                    created_by=admin_user,
                ),
                Event(
                    title="峰A活动",
                    status="upcoming",
                    visibility="peak",
                    peak_id=peak_a.id,
                    created_by=admin_user,
                ),
            ]
        )
        await db.flush()

        event_service = EventService(db)
        outsider_events, _ = await event_service.list_events(user=outsider)
        assert {e.title for e in outsider_events} >= {"公开活动"}
        assert "成员活动" not in {e.title for e in outsider_events}
        member_events, _ = await event_service.list_events(user=member)
        member_titles_set = {e.title for e in member_events}
        assert {"公开活动", "成员活动", "峰A活动"} <= member_titles_set
        other_events, _ = await event_service.list_events(user=other_member)
        assert "峰A活动" not in {e.title for e in other_events}

        await db.rollback()


async def test_announcement_admin_filter_created_by(admin_user):
    """管理端 created_by 过滤：只返回本人创建的公告。"""
    async with get_session() as db:
        sfx = uuid.uuid4().hex[:8]
        other = await _make_user(db, sfx, "author")
        db.add_all(
            [
                Announcement(
                    title=f"mine-{sfx}",
                    content="本人公告",
                    status="draft",
                    visibility="public",
                    is_active=False,
                    created_by=admin_user,
                ),
                Announcement(
                    title=f"other-{sfx}",
                    content="他人公告",
                    status="draft",
                    visibility="public",
                    is_active=False,
                    created_by=other.id,
                ),
            ]
        )
        await db.flush()

        service = AnnouncementService(db)
        titles = {item.title for item in await service.list_all(created_by=admin_user)}
        assert f"mine-{sfx}" in titles
        assert f"other-{sfx}" not in titles

        await db.rollback()
