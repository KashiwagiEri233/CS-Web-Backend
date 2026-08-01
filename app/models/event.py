"""活动模型：events / event_registrations / event_checkins / activity_participations。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class Event(Base):
    """活动：month/date/year 为展示用文本；capacity=0 表示不限人数。"""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    year: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    topics: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    tags: Mapped[Optional[list]] = mapped_column(JSONDict, nullable=True, default=list)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    content_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    # 报名表单字段定义（JSON 数组，如 [{"key":"qq","label":"QQ","required":true}]）
    registration_fields: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, title='{self.title}', status='{self.status}')>"


class EventRegistration(Base):
    """活动报名：(user_id, event_id) 唯一防止重复报名。"""

    __tablename__ = "event_registrations"

    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="ux_event_registrations_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="registered"
    )
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 报名表单提交内容（JSON 对象）
    form_data: Mapped[Optional[dict]] = mapped_column(JSONDict, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<EventRegistration(id={self.id}, user_id={self.user_id}, "
            f"event_id={self.event_id})>"
        )


class EventCheckin(Base):
    """活动签到：registration_id 唯一（一次报名只能签到一次）。"""

    __tablename__ = "event_checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id"), nullable=False, index=True
    )
    registration_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event_registrations.id"), nullable=True, unique=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    checkin_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    checked_in_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return f"<EventCheckin(id={self.id}, event_id={self.event_id})>"


class ActivityParticipation(Base):
    """用户主页活动参与记录：以标题+日期快照，避免依赖活动表外键。"""

    __tablename__ = "activity_participations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    activity_title: Mapped[str] = mapped_column(String(255), nullable=False)
    activity_date: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return f"<ActivityParticipation(id={self.id}, user_id={self.user_id})>"
