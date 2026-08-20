"""活动仓储（event_repo）真实 PostgreSQL 集成测试。

覆盖 ER-02 点名的四类零测试逻辑（在仓储层直接验证，区别于 test_phase3_events
的 service 层覆盖）：
- EventRepository：CRUD / 分页 / status·search 过滤 / auto_archive / batch_update_status；
- EventRegistrationRepository：报名唯一约束 / 状态流转 / count / stats / 列表；
- EventCheckinRepository：签到码生成·核销 / mark_checked_in / stats；
- EventSettingRepository：upsert / get_all / delete。

清理策略：events 的 created_by 外键默认 NO ACTION（不级联），且 registrations/
checkins 反向引用 events，因此清理顺序必须为 checkins → registrations → events
→ settings → users，否则触发外键约束。

注意：EventRepository.list_events 的 tag 过滤（event_repo.py:36）仍存在与
community 同源的 JSONB-LIKE 退化 bug（ER-23 点名范围之外，单独修复 MP 未覆盖），
本测试刻意不传 tag 参数，避免命中该缺陷；待后续决策是否并入 tag 修复 MP。

本地无法连接数据库时自动 skip；CI 严格模式下直接失败。
"""

import uuid

import pytest
from sqlalchemy import delete

from app.core.timezone import now_utc
from app.database import get_session
from app.models.event import Event, EventCheckin, EventRegistration
from app.models.setting import Setting
from app.models.user import User
from app.repositories.event_repo import (
    EventCheckinRepository,
    EventRegistrationRepository,
    EventRepository,
    EventSettingRepository,
)

pytestmark = pytest.mark.integration


async def _make_user(db, sfx: str) -> int:
    user = User(
        username=f"itest_evt_u_{sfx}",
        email=f"itest_evt_{sfx}@t.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user.id


async def _cleanup(
    db, uids: list[int], event_ids: list[int], setting_keys=None
) -> None:
    """按依赖顺序清场：checkins → registrations → events → settings → users。"""
    if event_ids:
        await db.execute(
            delete(EventCheckin).where(EventCheckin.event_id.in_(event_ids))
        )
        await db.execute(
            delete(EventRegistration).where(EventRegistration.event_id.in_(event_ids))
        )
        await db.execute(delete(Event).where(Event.id.in_(event_ids)))
    if setting_keys:
        await db.execute(
            delete(Setting).where(
                Setting.module == "events", Setting.key.in_(setting_keys)
            )
        )
    if uids:
        await db.execute(delete(User).where(User.id.in_(uids)))
    await db.commit()


# ---------------------------------------------------------------------------
# 1) EventRepository：CRUD + 分页 + status/search 过滤 + auto_archive + batch
# ---------------------------------------------------------------------------
async def test_event_crud_pagination_status_archive_batch(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
    event_ids: list[int] = []
    try:
        async with get_session() as db:
            repo = EventRepository(db)
            e1 = await repo.create(
                {
                    "title": f"evt-up-{sfx}",
                    "status": "upcoming",
                    "created_by": uid,
                    "date": "2099.12.31",
                }
            )
            e2 = await repo.create(
                {
                    "title": f"evt-ong-{sfx}",
                    "status": "ongoing",
                    "created_by": uid,
                    "date": "2099.12.31",
                }
            )
            e3 = await repo.create(
                {
                    "title": f"evt-end-{sfx}",
                    "status": "ended",
                    "created_by": uid,
                    "date": "2020.01.01",
                }
            )
            await db.commit()
            event_ids += [e1.id, e2.id, e3.id]

            # get_by_id（含 populate_existing 刷新）
            assert (await repo.get_by_id(e1.id)).title == f"evt-up-{sfx}"

            # status 过滤 + 分页
            up_list, up_total = await repo.list_events(
                status="upcoming", skip=0, limit=10
            )
            assert up_total == 1 and up_list[0].id == e1.id

            # search 命中全部 3 条
            srch, st = await repo.list_events(search=sfx, skip=0, limit=10)
            assert st == 3

            # list_all 包含新建项
            all_ev = await repo.list_all()
            assert all(e.id in event_ids for e in all_ev if e.title.endswith(sfx))

            # batch_update_status
            n = await repo.batch_update_status([e1.id, e2.id], "ongoing")
            assert n == 2
            await db.commit()
            assert (await repo.get_by_id(e1.id)).status == "ongoing"

            # auto_archive：过去日期 upcoming -> ended；未来日期不归档
            past = await repo.create(
                {
                    "title": f"evt-past-{sfx}",
                    "status": "upcoming",
                    "created_by": uid,
                    "date": "2020.01.01",
                }
            )
            await db.commit()
            event_ids.append(past.id)
            await repo.auto_archive("2099-12-31")
            await db.commit()
            assert (await repo.get_by_id(past.id)).status == "ended"

            # delete
            assert await repo.delete(e1.id) is True
            await db.commit()
            assert (await repo.get_by_id(e1.id)) is None
            assert await repo.delete(999999) is False
    finally:
        async with get_session() as db:
            await _cleanup(db, [uid], event_ids, None)


# ---------------------------------------------------------------------------
# 1.5) tag 过滤回归 —— list_events 的 tag 走 JSONB @> 包含
#      （2026-08-10 并入 tag 修复 MP：event_repo.py:36 原为字符串 LIKE 退化写法）
# ---------------------------------------------------------------------------
async def test_event_tag_filter_jsonb_containment(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
    event_ids: list[int] = []
    try:
        async with get_session() as db:
            repo = EventRepository(db)
            base = {
                "title": f"tag-evt-{sfx}",
                "status": "upcoming",
                "created_by": uid,
                "date": "2099.12.31",
            }
            for i in range(5):
                tag = "python" if i % 2 == 0 else "golang"
                e = await repo.create(
                    {**base, "title": f"tag-evt-{sfx}-{i}", "tags": [tag]}
                )
                event_ids.append(e.id)
            await db.commit()

            # 参数化 JSONB 包含：python 命中 3 条（i=0,2,4），golang 命中 2 条
            py_events, py_total = await repo.list_events(tag="python", skip=0, limit=10)
            assert py_total == 3
            assert all("python" in (e.tags or []) for e in py_events)
            go_events, go_total = await repo.list_events(tag="golang", skip=0, limit=10)
            assert go_total == 2

            # 注入型 tag 不应报错也不应匹配（参数化，绝不拼入 SQL）
            inj_events, inj_total = await repo.list_events(
                tag="python' OR '1'='1", skip=0, limit=10
            )
            assert inj_total == 0
    finally:
        async with get_session() as db:
            await _cleanup(db, [uid], event_ids, None)


# ---------------------------------------------------------------------------
# 2) EventRegistrationRepository：create / get / count / stats / 状态流转
# ---------------------------------------------------------------------------
async def test_registration_create_count_stats_status(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        organizer = await _make_user(db, f"{sfx}org")
        u1 = await _make_user(db, f"{sfx}u1")
        u2 = await _make_user(db, f"{sfx}u2")
    event_ids: list[int] = []
    try:
        async with get_session() as db:
            ev_repo = EventRepository(db)
            event = await ev_repo.create(
                {
                    "title": f"reg-evt-{sfx}",
                    "status": "upcoming",
                    "created_by": organizer,
                    "capacity": 0,
                }
            )
            await db.commit()
            event_ids.append(event.id)

            reg_repo = EventRegistrationRepository(db)
            r1 = await reg_repo.create(
                {
                    "user_id": u1,
                    "event_id": event.id,
                    "status": "registered",
                    "form_data": {"qq": "1"},
                }
            )
            r2 = await reg_repo.create(
                {
                    "user_id": u2,
                    "event_id": event.id,
                    "status": "registered",
                    "form_data": {"qq": "2"},
                }
            )
            await db.commit()

            # get / get_by_id
            assert (await reg_repo.get(u1, event.id)) is not None
            assert (await reg_repo.get_by_id(r1.id)) is not None

            # count_registered == 2
            assert await reg_repo.count_registered(event.id) == 2

            # 列表
            assert len(await reg_repo.list_for_event(event.id)) == 2
            assert len(await reg_repo.list_registered_for_event(event.id)) == 2

            # stats_for_event
            stats = await reg_repo.stats_for_event(event.id)
            assert stats["total"] == 2 and stats["registered"] == 2

            # 状态流转：取消 u1 -> registered 计数降为 1
            reg1 = await reg_repo.get(u1, event.id)
            await reg_repo.set_status(reg1, "cancelled", cancelled_at=now_utc())
            await db.commit()
            assert await reg_repo.count_registered(event.id) == 1
            stats2 = await reg_repo.stats_for_event(event.id)
            assert stats2["cancelled"] == 1 and stats2["registered"] == 1

            # 用户全部报名记录
            mine = await reg_repo.list_for_user_all(u1)
            assert any(r.id == r1.id for r in mine)

            # 跨活动统计包含本活动
            sae = await reg_repo.stats_all_events()
            assert any(s["event_id"] == event.id for s in sae)
    finally:
        async with get_session() as db:
            await _cleanup(db, [organizer, u1, u2], event_ids, None)


# ---------------------------------------------------------------------------
# 3) EventRegistrationRepository：唯一约束 (user_id, event_id) 防重复报名
# ---------------------------------------------------------------------------
async def test_registration_unique_constraint(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        organizer = await _make_user(db, f"{sfx}org")
        u1 = await _make_user(db, f"{sfx}u1")
    event_ids: list[int] = []
    try:
        async with get_session() as db:
            ev_repo = EventRepository(db)
            event = await ev_repo.create(
                {
                    "title": f"uniq-evt-{sfx}",
                    "status": "upcoming",
                    "created_by": organizer,
                }
            )
            # flush 的 RETURNING 已写入内存，立即抓出纯 int id，
            # 避免后续失败事务导致 event 实例 detached 后访问 .id 触发惰性重载
            event_id = event.id
            await db.commit()
            event_ids.append(event_id)

            reg_repo = EventRegistrationRepository(db)
            await reg_repo.create(
                {"user_id": u1, "event_id": event_id, "status": "registered"}
            )
            await db.commit()

            # 重复报名在 create() 内部的 flush 时触发 UniqueConstraint -> IntegrityError
            # （repo.create 自带 flush，异常自 create 抛出，须在此处捕获）
            with pytest.raises(Exception):
                await reg_repo.create(
                    {"user_id": u1, "event_id": event_id, "status": "registered"}
                )
            await db.rollback()

            # 回滚后仅保留 1 条有效报名（用纯 int event_id，不触碰 detached 实例）
            assert await reg_repo.count_registered(event_id) == 1
    finally:
        async with get_session() as db:
            await _cleanup(db, [organizer, u1], event_ids, None)


# ---------------------------------------------------------------------------
# 4) EventCheckinRepository：create / get_by_code / mark_checked_in / stats
# ---------------------------------------------------------------------------
async def test_checkin_create_get_mark_stats(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        organizer = await _make_user(db, f"{sfx}org")
        u1 = await _make_user(db, f"{sfx}u1")
    event_ids: list[int] = []
    try:
        async with get_session() as db:
            ev_repo = EventRepository(db)
            event = await ev_repo.create(
                {
                    "title": f"ck-evt-{sfx}",
                    "status": "upcoming",
                    "created_by": organizer,
                }
            )
            await db.commit()
            event_ids.append(event.id)

            reg_repo = EventRegistrationRepository(db)
            reg = await reg_repo.create(
                {"user_id": u1, "event_id": event.id, "status": "registered"}
            )
            await db.commit()
            reg_id = reg.id

            ck_repo = EventCheckinRepository(db)
            code = f"CODE-{sfx}"
            ck = await ck_repo.create(
                event_id=event.id,
                registration_id=reg_id,
                user_id=u1,
                checkin_code=code,
            )
            await db.commit()
            assert ck.id is not None

            # get_by_code
            fetched = await ck_repo.get_by_code(event.id, code)
            assert fetched is not None and fetched.id == ck.id

            # list_for_event
            assert len(await ck_repo.list_for_event(event.id)) == 1

            # mark_checked_in（仅改属性，需提交）
            await ck_repo.mark_checked_in(fetched, by_user_id=organizer)
            await db.commit()

            # 新会话核验核销写入
            async with get_session() as db2:
                f2 = await EventCheckinRepository(db2).get_by_code(event.id, code)
                assert f2.checked_in_at is not None
                assert f2.checked_in_by == organizer

            # stats_for_event
            async with get_session() as db3:
                stats = await EventCheckinRepository(db3).stats_for_event(event.id)
                assert stats["total"] == 1 and stats["checked_in"] == 1
    finally:
        async with get_session() as db:
            await _cleanup(db, [organizer, u1], event_ids, None)


# ---------------------------------------------------------------------------
# 5) EventSettingRepository：upsert / get_all / delete
# ---------------------------------------------------------------------------
async def test_setting_upsert_get_all_delete(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    k1 = f"itest_evt_{sfx}_a"
    k2 = f"itest_evt_{sfx}_b"
    try:
        async with get_session() as db:
            repo = EventSettingRepository(db)
            await repo.upsert(k1, "v1")
            await repo.upsert(k2, "v2")
            await db.commit()

            all_settings = await repo.get_all()
            assert all_settings.get(k1) == "v1"
            assert all_settings.get(k2) == "v2"

            # upsert 覆盖同键
            await repo.upsert(k1, "v1-updated")
            await db.commit()
            assert (await repo.get_all()).get(k1) == "v1-updated"

            # delete 移除键
            await repo.delete(k2)
            await db.commit()
            assert (await repo.get_all()).get(k2) is None
    finally:
        async with get_session() as db:
            await db.execute(
                delete(Setting).where(
                    Setting.module == "events", Setting.key.in_([k1, k2])
                )
            )
            await db.commit()
