"""组织模型：峰（peaks）与成员档案（member_profiles）。

设计说明（本期轻量实现）：
- 峰是组织归属的唯一事实源，不再保存第二份可变钱包余额（资金统一走 wallet 账本）。
- 成员档案与 users 一对一；身份字段来自 users，本表只保存协会成员状态、学号与所属峰。
- 角色与作用范围在 user_roles 绑定实体中表达，本表不重复保存 role 字符串。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime as _DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class Peak(Base):
    """组织分组（旧端称「峰」）。"""

    __tablename__ = "peaks"
    __table_args__ = (
        UniqueConstraint("code", name="uq_peaks_code"),
        Index("ix_peaks_active_archived", "is_active", "archived_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 旧端展示名（如「剑峰」）；为空时回退 name
    fantasy_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<Peak(id={self.id}, code='{self.code}')>"


class MemberProfile(Base):
    """协会成员档案：与 users 一对一，补充学号、所属峰与成员状态。"""

    __tablename__ = "member_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_member_profiles_user_id"),
        # 学号允许为空；非空时唯一（部分唯一索引，避免 NULL 冲突）
        Index(
            "uq_member_profiles_student_id",
            "student_id",
            unique=True,
            postgresql_where=text("student_id IS NOT NULL"),
        ),
        Index("ix_member_profiles_peak_status", "peak_id", "membership_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    peak_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("peaks.id", ondelete="SET NULL"),
        nullable=True,
    )
    # active | suspended | left
    membership_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<MemberProfile(id={self.id}, user_id={self.user_id})>"
