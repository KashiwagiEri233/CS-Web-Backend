"""Agent 每日学习简报模型（AG-P3-03）。

移植 Aervox diary 域的「素材窗口采集 → 生成 → 存储」管线
（RootDoc-AgentEval.md §2）：每用户每日一份（user_id + brief_date 唯一，
天然内容去重）；生成失败落 failed 状态，不影响工作台读取。
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


class AgentDailyBriefing(Base):
    """每日学习简报：规则聚合 v1（LLM 生成后接），内容为分节 JSON。"""

    __tablename__ = "agent_daily_briefings"
    # 内容去重：每用户每日仅一份（同日重读返回既有记录）
    __table_args__ = (
        UniqueConstraint("user_id", "brief_date", name="uq_agent_briefing_user_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brief_date: Mapped[date] = mapped_column(Date, nullable=False)
    # 分节内容：{"reviews": n, "focusMinutes": m, "tasks": k, "community": p,
    #            "inboxPending": q}；采集失败的节为 null
    content: Mapped[Optional[dict]] = mapped_column(JSONDict, nullable=True)
    # ready = 生成成功；failed = 采集过程异常（工作台侧静默降级）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return (
            f"<AgentDailyBriefing(id={self.id}, user_id={self.user_id}, "
            f"brief_date={self.brief_date}, status='{self.status}')>"
        )
