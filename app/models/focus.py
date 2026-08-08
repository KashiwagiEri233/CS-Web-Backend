"""专注记录模型：focus_sessions（番茄钟完成一轮专注后上报）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class FocusSession(Base):
    """一轮已完成的专注会话（前端番茄钟上报）。"""

    __tablename__ = "focus_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(
        String(20), nullable=False, default="focus"
    )  # focus | shortBreak | longBreak
    # 专注期间的声音来源（ambient 环境音名 / upload 音乐 / silence）
    sound_source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # 本轮开始的近似时间（上报时按 duration 反推）
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return f"<FocusSession(user={self.user_id}, {self.duration_seconds}s)>"
