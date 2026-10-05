"""Agent 每周复盘模型（AG-P3-04）。

复用 AG-P3-03 简报的素材管线，聚合到周窗口：每用户每周一份
(user_id + week_start 唯一，week_start 为配置时区周一)；数字均可追溯
数据源，模型只负责解释（LLM 摘要后接）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class AgentWeeklyReview(Base):
    """每周复盘：分节 JSON（专注/错题/任务/社区/计划达成 + 下周建议）。"""

    __tablename__ = "agent_weekly_reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_agent_review_user_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[Optional[dict]] = mapped_column(JSONDict, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return (
            f"<AgentWeeklyReview(id={self.id}, user_id={self.user_id}, "
            f"week_start={self.week_start}, status='{self.status}')>"
        )
