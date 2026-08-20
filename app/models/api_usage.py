"""API 调用日志模型：api_call_logs（学习助手/全站 API 可观测性埋点）。"""

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


class ApiCallLog(Base):
    """一次 API 请求的调用记录（中间件 fire-and-forget 写入）。"""

    __tablename__ = "api_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

    def __repr__(self) -> str:
        return f"<ApiCallLog({self.method} {self.endpoint} {self.status})>"
