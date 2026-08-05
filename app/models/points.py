"""积分流水模型：points_transactions，记录变更后余额便于审计对账。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime as _DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class PointsTransaction(Base):
    """积分流水：amount 可为负（消费/扣除）；balance_after 为变更后余额。"""

    __tablename__ = "points_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="system"
    )
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

    def __repr__(self) -> str:
        return (
            f"<PointsTransaction(id={self.id}, user_id={self.user_id}, "
            f"amount={self.amount})>"
        )
