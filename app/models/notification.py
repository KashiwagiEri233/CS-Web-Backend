"""通知模型：notifications（站内信）/ announcements（全站公告）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime as _DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class Notification(Base):
    """站内通知：type 区分来源（reply/mention/system/event 等）。"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sender_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, user_id={self.user_id}, type='{self.type}')>"
        )


class Announcement(Base):
    """全站公告：可见范围 + 发布状态；target_roles 为附加角色条件。

    is_active 为兼容展示字段，由 status 派生（published → True）。
    """

    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_announcements_status",
        ),
        CheckConstraint(
            "visibility IN ('public', 'members', 'peak')",
            name="ck_announcements_visibility",
        ),
        CheckConstraint(
            "visibility <> 'peak' OR peak_id IS NOT NULL",
            name="ck_announcements_peak_visibility",
        ),
        Index("ix_announcements_status_published", "status", "published_at", "id"),
        Index("ix_announcements_expires", "expires_at"),
        Index("ix_announcements_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_dismissible: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 定向角色（JSON 数组）；NULL = 全员可见
    target_roles: Mapped[Optional[list]] = mapped_column(JSONDict, nullable=True)
    # 组织可见范围
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="public"
    )
    peak_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("peaks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return (
            f"<Announcement(id={self.id}, title='{self.title}', "
            f"is_active={self.is_active})>"
        )
