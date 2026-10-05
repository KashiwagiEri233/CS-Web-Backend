"""Agent 自动化规则模型（AG-P3-02）。

移植 Aervox CR-032 / CAP-030 的防打扰裁决器参数模型（冷却 / 静音时段 /
每小时频次水位，见 RootDoc-AgentEval.md §2）：规则由用户逐条启停，
默认不启用；触发器（AG-P3-05）产生建议前 MUST 先经裁决器放行。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class AgentAutomationRule(Base):
    """用户级自动化规则：触发条件 → 经裁决器 → 生成收件箱建议。"""

    __tablename__ = "agent_automation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 触发类型（服务层白名单校验），对应 AG-P3-05 的触发器实现
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 触发条件（JSONB）：如 {"knowledgePoint": "dp", "minWrongCount": 3}；NULL = 无附加条件
    condition: Mapped[Optional[dict]] = mapped_column(JSONDict, nullable=True)
    # 建议动作（v1 仅 inbox_suggestion：生成一条收件箱建议）
    action_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="inbox_suggestion"
    )
    action_payload: Mapped[Optional[dict]] = mapped_column(JSONDict, nullable=True)
    # ---- CR-032 裁决器三参数 ----
    quiet_hours_start: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    quiet_hours_end: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=240)
    max_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # 用户逐条启停（默认不启用："默认不开启高频通知"）
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    # 最近一次放行时间（裁决器冷却判定 + 观测）
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return (
            f"<AgentAutomationRule(id={self.id}, user_id={self.user_id}, "
            f"trigger_type='{self.trigger_type}', enabled={self.enabled})>"
        )
