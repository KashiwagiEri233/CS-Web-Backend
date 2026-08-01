"""入社申请模型：线上申请 → 管理员审批 → 开通账号。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime as _DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class JoinApplication(Base):
    """入社申请：status = pending | approved | rejected。"""

    __tablename__ = "join_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    applicant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    student_id: Mapped[str] = mapped_column(String(50), nullable=False)
    major: Mapped[str] = mapped_column(String(100), nullable=False)
    # 技术方向标签（JSON 数组）
    tech_tags: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    contact_qq: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return (
            f"<JoinApplication(id={self.id}, name='{self.applicant_name}', "
            f"status='{self.status}')>"
        )
