"""登录历史模型：记录每次登录成功/失败，用于安全监控与异常登录检测。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
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

DateTime = _DateTime(timezone=True)


class LoginHistory(Base):
    """登录历史：user_id 可空（登录失败时无对应用户）；attempted_email 用于检测撞库。"""

    __tablename__ = "login_history"

    # 索引对齐查询形态：「按 user/attempted_email 过滤 + 恒定 ORDER BY created_at DESC」，
    # (过滤列, created_at) 复合索引可同时吃掉过滤与排序。
    __table_args__ = (
        Index("idx_login_history_user", "user_id", "created_at"),
        Index("idx_login_history_attempted_email", "attempted_email", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    attempted_email: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<LoginHistory(id={self.id}, user_id={self.user_id}, "
            f"success={self.success})>"
        )
