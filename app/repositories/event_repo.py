"""活动仓储：events / event_registrations / event_checkins / settings。"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import Integer, func, or_, select, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.event import Event, EventCheckin, EventRegistration
from app.models.setting import Setting
from app.repositories.base import dml_rowcount
from app.repositories.base import paginate
from app.core.query_helpers import jsonb_contains


class EventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_events(
        self,
        *,
        status: Optional[str] = None,
        search: Optional[str] = None,
        tag: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Event], int]:
        conditions: list = []
        if status:
            conditions.append(Event.status == status)
        if search and search.strip():
            kw = f"%{search.strip()}%"
            conditions.append(or_(Event.title.ilike(kw), Event.description.ilike(kw)))
        if tag and tag.strip():
            # 2026-08-10 修复：Event.tags 为 JSON().with_variant(JSONB(),"postgresql")
            # （Variant），ColumnElement.contains 会退化成通用字符串 LIKE（编译为
            # `col LIKE '%' || $n::JSONB || '%'`），实际调用抛 invalid input syntax
            # for type json。type_coerce(..., JSONB).contains([tag]) 走 JSONB `@>`。
            conditions.append(jsonb_contains(Event.tags, [tag.strip()]))

        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Event).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(Event)
            .where(*conditions)
            .order_by(Event.is_pinned.desc(), Event.date.desc()),
            skip, limit
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def list_all(self) -> list[Event]:
        stmt = select(Event).order_by(Event.is_pinned.desc(), Event.date.desc())
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_id(self, event_id: int) -> Optional[Event]:
        # populate_existing：即便对象已在 identity map（含批量更新后的过期状态）
        # 也强制从 DB 刷新，保证返回最新状态
        stmt = (
            select(Event)
            .where(Event.id == event_id)
            .execution_options(populate_existing=True)
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def create(self, data: dict) -> Event:
        obj = Event(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete(self, event_id: int) -> bool:
        obj = await self.get_by_id(event_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def auto_archive(self, now_date: str) -> int:
        """将已过日期的活动自动标记为 ended（date 为自由格式字符串，归一化比较）。"""
        from sqlalchemy import text

        result = await self.db.execute(
            text("""
                UPDATE events SET status = 'ended', updated_at = :now
                WHERE status != 'ended' AND date IS NOT NULL AND date != ''
                  AND substr(REPLACE(REPLACE(date, '.', '-'), '/', '-'), 1, 10) < :today
                """),
            {"now": now_utc(), "today": now_date},
        )
        return dml_rowcount(result)

    async def batch_update_status(self, event_ids: Sequence[int], status: str) -> int:
        result = await self.db.execute(
            update(Event)
            .where(Event.id.in_(event_ids))
            .values(status=status, updated_at=now_utc())
        )
        return dml_rowcount(result)


class EventRegistrationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: int, event_id: int) -> Optional[EventRegistration]:
        stmt = select(EventRegistration).where(
            EventRegistration.user_id == user_id,
            EventRegistration.event_id == event_id,
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def get_by_id(self, registration_id: int) -> Optional[EventRegistration]:
        return await self.db.get(EventRegistration, registration_id)

    async def list_for_event(self, event_id: int) -> list[EventRegistration]:
        stmt = (
            select(EventRegistration)
            .where(EventRegistration.event_id == event_id)
            .order_by(EventRegistration.registered_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_registered_for_event(self, event_id: int) -> list[EventRegistration]:
        stmt = (
            select(EventRegistration)
            .where(
                EventRegistration.event_id == event_id,
                EventRegistration.status == "registered",
            )
            .order_by(EventRegistration.registered_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_for_user_all(self, user_id: int) -> list[EventRegistration]:
        """用户全部报名记录（含已取消）。"""
        stmt = (
            select(EventRegistration)
            .where(EventRegistration.user_id == user_id)
            .order_by(EventRegistration.registered_at.desc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def create(self, data: dict) -> EventRegistration:
        obj = EventRegistration(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def set_status(
        self, reg: EventRegistration, status: str, cancelled_at=None
    ) -> None:
        reg.status = status
        reg.cancelled_at = cancelled_at

    async def count_registered(self, event_id: int) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(EventRegistration)
                    .where(
                        EventRegistration.event_id == event_id,
                        EventRegistration.status == "registered",
                    )
                )
            ).scalar_one()
        )

    async def stats_for_event(self, event_id: int) -> dict:
        rows = (
            await self.db.execute(
                select(
                    EventRegistration.status,
                    func.count().label("count"),
                )
                .where(EventRegistration.event_id == event_id)
                .group_by(EventRegistration.status)
            )
        ).all()
        stats = {"total": 0, "registered": 0, "cancelled": 0, "waitlisted": 0}
        for status, count in rows:
            stats["total"] += count
            if status in stats:
                stats[status] = count
        return stats

    async def stats_all_events(self) -> list[dict]:
        rows = (
            await self.db.execute(
                select(
                    Event.id,
                    Event.title,
                    Event.capacity,
                    func.count(EventRegistration.id).label("total"),
                    func.sum(
                        (EventRegistration.status == "registered").cast(Integer)
                    ).label("registered"),
                    func.sum(
                        (EventRegistration.status == "cancelled").cast(Integer)
                    ).label("cancelled"),
                    func.sum(
                        (EventRegistration.status == "waitlisted").cast(Integer)
                    ).label("waitlisted"),
                )
                .outerjoin(EventRegistration, EventRegistration.event_id == Event.id)
                .group_by(Event.id)
                .order_by(Event.date.desc())
            )
        ).all()
        result = []
        for row in rows:
            result.append(
                {
                    "event_id": row.id,
                    "title": row.title,
                    "capacity": row.capacity or 0,
                    "total": row.total or 0,
                    "registered": row.registered or 0,
                    "cancelled": row.cancelled or 0,
                    "waitlisted": row.waitlisted or 0,
                }
            )
        return result


class EventCheckinRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self, *, event_id: int, registration_id: int, user_id: int, checkin_code: str
    ) -> EventCheckin:
        obj = EventCheckin(
            event_id=event_id,
            registration_id=registration_id,
            user_id=user_id,
            checkin_code=checkin_code,
        )
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_by_code(self, event_id: int, code: str) -> Optional[EventCheckin]:
        stmt = select(EventCheckin).where(
            EventCheckin.event_id == event_id,
            EventCheckin.checkin_code == code,
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def list_for_event(self, event_id: int) -> list[EventCheckin]:
        stmt = (
            select(EventCheckin)
            .where(EventCheckin.event_id == event_id)
            .order_by(EventCheckin.created_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def mark_checked_in(self, checkin: EventCheckin, by_user_id: int) -> None:
        checkin.checked_in_at = now_utc()
        checkin.checked_in_by = by_user_id

    async def stats_for_event(self, event_id: int) -> dict:
        rows = (
            await self.db.execute(
                select(
                    func.count().label("total"),
                    func.sum(
                        (EventCheckin.checked_in_at.is_not(None)).cast(Integer)
                    ).label("checked_in"),
                ).where(EventCheckin.event_id == event_id)
            )
        ).one()
        total = rows.total or 0
        checked_in = rows.checked_in or 0
        return {
            "total": total,
            "checked_in": checked_in,
            "not_checked_in": total - checked_in,
        }


class EventSettingRepository:
    """活动设置（settings 表 module=events）。"""

    MODULE = "events"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> dict[str, str]:
        stmt = select(Setting).where(Setting.module == self.MODULE)
        rows = await self.db.execute(stmt)
        return {row.key: row.value for row in rows.scalars().all()}

    async def upsert(self, key: str, value: str) -> None:
        stmt = select(Setting).where(Setting.module == self.MODULE, Setting.key == key)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            self.db.add(Setting(module=self.MODULE, key=key, value=value))
        else:
            row.value = value
            row.updated_at = now_utc()
        await self.db.flush()

    async def delete(self, key: str) -> None:
        stmt = select(Setting).where(Setting.module == self.MODULE, Setting.key == key)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is not None:
            await self.db.delete(row)
