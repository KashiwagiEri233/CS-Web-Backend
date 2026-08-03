"""活动服务：CRUD / 报名（限额+唯一约束）/ 签到核销 / 归档 / 设置 / 统计。

业务事件（event.created / event.registered / event.cancelled）经 event_bus 发布，
通知订阅者见 app/services/notification_events.py。
"""

from __future__ import annotations

import secrets
from datetime import date as date_cls
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.timezone import now_utc
from app.models.event import Event, EventCheckin, EventRegistration
from app.repositories.event_repo import (
    EventCheckinRepository,
    EventRegistrationRepository,
    EventRepository,
    EventSettingRepository,
)
from app.schemas.event import EVENT_LIMITS, EventInput, EventSettingsIn
from app.services.audit_service import AuditService


class EventService:
    def __init__(self, db: AsyncSession, audit: Optional[AuditService] = None):
        self.db = db
        self.event_repo = EventRepository(db)
        self.reg_repo = EventRegistrationRepository(db)
        self.checkin_repo = EventCheckinRepository(db)
        self.setting_repo = EventSettingRepository(db)
        self.audit = audit if audit is not None else AuditService()

    # ------------------------------------------------------------------ 设置

    async def get_settings(self) -> dict:
        """活动设置：DB 覆盖默认值。"""
        stored = await self.setting_repo.get_all()
        settings = dict(EVENT_LIMITS)
        for key, value in stored.items():
            if key in settings:
                try:
                    parsed = float(value)
                    if parsed == int(parsed):
                        settings[key] = int(parsed)
                except (TypeError, ValueError):
                    pass
        return settings

    async def update_settings(self, data: EventSettingsIn) -> dict:
        """批量更新设置项（支持 dict 或属性访问对象）。"""
        for key in EVENT_LIMITS:
            value = (
                data.get(key) if isinstance(data, dict) else getattr(data, key, None)
            )
            if value is not None:
                await self.setting_repo.upsert(key, str(value))
        await self.db.commit()
        return await self.get_settings()

    async def reset_setting(self, key: str) -> dict:
        if key not in EVENT_LIMITS:
            raise ValidationException(
                message="无效的 key", error_code=ErrorCode.Validation.VALIDATION_FAILED
            )
        await self.setting_repo.delete(key)
        await self.db.commit()
        return await self.get_settings()

    # ------------------------------------------------------------------ CRUD

    async def auto_archive(self) -> int:
        """自动归档：日期已过的活动标记 ended。"""
        return await self.event_repo.auto_archive(date_cls.today().isoformat())

    async def list_events(
        self,
        *,
        status: Optional[str] = None,
        search: Optional[str] = None,
        tag: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Event], int]:
        await self.auto_archive()
        events, total = await self.event_repo.list_events(
            status=status, search=search, tag=tag, skip=skip, limit=limit
        )
        # 附报名人数
        for event in events:
            count = await self.reg_repo.count_registered(event.id)
            setattr(event, "registered_count", count)
        return events, total

    async def get_event(self, event_id: int) -> Event:
        await self.auto_archive()
        event = await self.event_repo.get_by_id(event_id)
        if event is None:
            raise NotFoundException(
                message="活动不存在", resource_type="event", resource_id=str(event_id)
            )
        count = await self.reg_repo.count_registered(event_id)
        setattr(event, "registered_count", count)
        return event

    async def create_event(
        self, created_by: int, data: EventInput, client_meta=None
    ) -> Event:
        payload = data.model_dump()
        payload["created_by"] = created_by
        event = await self.event_repo.create(payload)
        await self.db.commit()

        await self._audit(
            "event.create", created_by, event, {"title": event.title}, client_meta
        )
        # 业务事件：新活动 → 全站广播通知
        event_bus.emit(
            "event.created",
            event_id=event.id,
            title=event.title,
            description=event.description,
            admin_id=created_by,
        )
        return event

    async def update_event(
        self, admin_id: int, event_id: int, data: EventInput, client_meta=None
    ) -> Event:
        event = await self.get_event(event_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(event, key, value)
        await self.db.commit()
        await self.db.refresh(event)
        await self._audit(
            "event.update",
            admin_id,
            event,
            {"fields": list(data.model_dump(exclude_unset=True).keys())},
            client_meta,
        )
        return event

    async def delete_event(
        self, admin_id: int, event_id: int, client_meta=None
    ) -> None:
        event = await self.event_repo.get_by_id(event_id)
        if event is None:
            raise NotFoundException(
                message="活动不存在", resource_type="event", resource_id=str(event_id)
            )
        title = event.title
        await self.event_repo.delete(event_id)
        await self.db.commit()
        await self._audit(
            "event.delete",
            admin_id,
            None,
            {"event_id": event_id, "title": title},
            client_meta,
        )

    async def batch_update(
        self, admin_id: int, event_ids: list[int], status: str, client_meta=None
    ) -> dict:
        if not status:
            raise ValidationException(
                message="未指定任何操作",
                error_code=ErrorCode.Validation.VALIDATION_FAILED,
            )
        success = await self.event_repo.batch_update_status(event_ids, status)
        await self.db.commit()
        await self._audit(
            "event.batch_update",
            admin_id,
            None,
            {"event_ids": event_ids, "status": status},
            client_meta,
        )
        return {"success": success, "failed": len(event_ids) - success}

    # ------------------------------------------------------------------ 报名

    async def get_user_registration(
        self, user_id: int, event_id: int
    ) -> Optional[EventRegistration]:
        return await self.reg_repo.get(user_id, event_id)

    async def register(
        self, user_id: int, event_id: int, form_data: Optional[dict] = None
    ) -> EventRegistration:
        event = await self.event_repo.get_by_id(event_id)
        if event is None:
            raise NotFoundException(
                message="活动不存在", resource_type="event", resource_id=str(event_id)
            )

        existing = await self.reg_repo.get(user_id, event_id)
        if existing is not None and existing.status == "registered":
            raise ConflictException(
                message="已报名该活动", error_code=ErrorCode.Conflict.ALREADY_REGISTERED
            )

        registered = await self.reg_repo.count_registered(event_id)
        if event.capacity > 0 and registered >= event.capacity:
            raise ConflictException(
                message="活动报名已满", error_code=ErrorCode.Conflict.FULL
            )

        if existing is not None:  # cancelled → 重新报名
            await self.reg_repo.set_status(existing, "registered", None)
            existing.form_data = form_data
            reg = existing
        else:
            reg = await self.reg_repo.create(
                {
                    "user_id": user_id,
                    "event_id": event_id,
                    "status": "registered",
                    "form_data": form_data,
                }
            )
        await self.db.commit()

        event_bus.emit(
            "event.registered",
            user_id=user_id,
            event_id=event_id,
            event_title=event.title,
        )
        return reg

    async def cancel(self, user_id: int, event_id: int) -> None:
        reg = await self.reg_repo.get(user_id, event_id)
        if reg is None:
            raise NotFoundException(
                message="报名记录不存在",
                resource_type="event_registration",
                resource_id=str(event_id),
            )
        if reg.status == "cancelled":
            raise ConflictException(
                message="报名已取消", error_code=ErrorCode.Conflict.ALREADY_CANCELLED
            )
        await self.reg_repo.set_status(reg, "cancelled", now_utc())
        await self.db.commit()

        event = await self.event_repo.get_by_id(event_id)
        event_bus.emit(
            "event.cancelled",
            user_id=user_id,
            event_id=event_id,
            event_title=event.title if event else "",
        )

    async def list_user_registered_events(self, user_id: int) -> list[Event]:
        """用户已报名的活动（registered 状态）。"""
        await self.auto_archive()
        regs = await self.reg_repo.list_for_user_all(user_id)
        events = []
        for reg in regs:
            event = await self.event_repo.get_by_id(reg.event_id)
            if event is not None:
                events.append(event)
        return events

    async def list_event_registrations(self, event_id: int) -> list[EventRegistration]:
        return await self.reg_repo.list_for_event(event_id)

    async def registration_stats(self, event_id: int) -> dict:
        return await self.reg_repo.stats_for_event(event_id)

    async def admin_update_registration_status(
        self, admin_id: int, registration_id: int, status: str, client_meta=None
    ) -> EventRegistration:
        reg = await self.reg_repo.get_by_id(registration_id)
        if reg is None:
            raise NotFoundException(
                message="报名记录不存在",
                resource_type="event_registration",
                resource_id=str(registration_id),
            )
        cancelled_at = now_utc() if status == "cancelled" else None
        await self.reg_repo.set_status(reg, status, cancelled_at)
        await self.db.commit()
        await self._audit(
            "event.registration_update",
            admin_id,
            None,
            {
                "registration_id": registration_id,
                "event_id": reg.event_id,
                "status": status,
            },
            client_meta,
        )
        return reg

    async def admin_add_registration(
        self,
        admin_id: int,
        user_id: int,
        event_id: int,
        form_data: Optional[dict] = None,
        client_meta=None,
    ) -> EventRegistration:
        event = await self.event_repo.get_by_id(event_id)
        if event is None:
            raise NotFoundException(
                message="活动不存在", resource_type="event", resource_id=str(event_id)
            )
        existing = await self.reg_repo.get(user_id, event_id)
        if existing is not None and existing.status == "registered":
            raise ConflictException(
                message="该用户已报名此活动",
                error_code=ErrorCode.Conflict.ALREADY_REGISTERED,
            )
        registered = await self.reg_repo.count_registered(event_id)
        if event.capacity > 0 and registered >= event.capacity:
            raise ConflictException(
                message="活动名额已满", error_code=ErrorCode.Conflict.FULL
            )
        if existing is not None:
            await self.reg_repo.set_status(existing, "registered", None)
            existing.form_data = form_data
            reg = existing
        else:
            reg = await self.reg_repo.create(
                {
                    "user_id": user_id,
                    "event_id": event_id,
                    "status": "registered",
                    "form_data": form_data,
                }
            )
        await self.db.commit()
        await self._audit(
            "event.registration_add",
            admin_id,
            user_id,
            {"event_id": event_id, "event_title": event.title},
            client_meta,
        )
        return reg

    # ------------------------------------------------------------------ 签到

    async def generate_checkin_codes(
        self, admin_id: int, event_id: int, client_meta=None
    ) -> dict:
        event = await self.event_repo.get_by_id(event_id)
        if event is None:
            raise NotFoundException(
                message="活动不存在", resource_type="event", resource_id=str(event_id)
            )
        regs = await self.reg_repo.list_registered_for_event(event_id)
        generated = 0
        skipped = 0
        existing_codes = {
            c.registration_id for c in await self.checkin_repo.list_for_event(event_id)
        }
        for reg in regs:
            if reg.id in existing_codes:
                skipped += 1
                continue
            code = f"{secrets.randbelow(900000) + 100000}"
            await self.checkin_repo.create(
                event_id=event_id,
                registration_id=reg.id,
                user_id=reg.user_id,
                checkin_code=code,
            )
            generated += 1
        await self.db.commit()
        await self._audit(
            "event.checkin_generate",
            admin_id,
            None,
            {"event_id": event_id, "generated": generated, "skipped": skipped},
            client_meta,
        )
        return {"generated": generated, "skipped": skipped}

    async def list_checkins(self, event_id: int) -> list[EventCheckin]:
        return await self.checkin_repo.list_for_event(event_id)

    async def checkin_stats(self, event_id: int) -> dict:
        return await self.checkin_repo.stats_for_event(event_id)

    async def checkin_by_code(
        self, admin_id: int, event_id: int, code: str, client_meta=None
    ) -> dict:
        checkin = await self.checkin_repo.get_by_code(event_id, code)
        if checkin is None:
            return {"ok": False, "error": "签到码无效"}
        if checkin.checked_in_at is not None:
            return {
                "ok": False,
                "error": f"该签到码已于 {checkin.checked_in_at.isoformat()} 使用",
            }
        await self.checkin_repo.mark_checked_in(checkin, admin_id)
        await self.db.commit()
        await self._audit(
            "event.checkin",
            admin_id,
            checkin.user_id,
            {"event_id": event_id, "checkin_id": checkin.id},
            client_meta,
        )
        return {"ok": True, "checkin": checkin}

    async def stats_all(self) -> list[dict]:
        return await self.reg_repo.stats_all_events()

    # ------------------------------------------------------------------ 内部

    async def _audit(
        self, action: str, actor_id: int, target, detail: dict, client_meta
    ) -> None:
        from app.models.user import User

        user = await self.db.get(User, actor_id)
        resource_id = (
            str(target.id)
            if hasattr(target, "id")
            else (str(target) if target is not None else None)
        )
        await self.audit.record(
            action=action,
            resource_type="event",
            resource_id=resource_id,
            actor_id=actor_id,
            actor_username=user.username if user else None,
            detail=detail,
            **(client_meta or {}),
        )
