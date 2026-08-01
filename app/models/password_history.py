"""历史密码模型：记录用户历史密码哈希，用于密码复用检测。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime as _DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class PasswordHistory(Base):
    """历史密码：按 (user_id, created_at DESC) 查询最近的 N 条做复用检测。"""

    __tablename__ = "password_history"

    __table_args__ = (Index("idx_password_history_user", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return f"<PasswordHistory(id={self.id}, user_id={self.user_id})>"
