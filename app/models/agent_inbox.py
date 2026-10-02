"""Agent 建议收件箱模型（AG-P3-01）。

移植自 Aervox-harness agent_inbox_items 的模式（幂等键 / 来源绑定 / 过期 / 状态机），
消费方从 Agent executor 改为用户本人：建议由触发器（AG-P3-05）或调度（AG-P3-06）产生，
用户在工作台统一接受 / 忽略 / 稍后处理，全程可追踪。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime as _DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class AgentInboxItem(Base):
    """用户级 Agent 建议项：一次产生、幂等去重、状态机闭环。"""

    __tablename__ = "agent_inbox_items"
    __table_args__ = (
        # 幂等键按用户去重：同一触发器重复生成同一建议时只保留一条（AG-P3-05 冷却/去重键）
        UniqueConstraint("user_id", "idempotency_key", name="uq_inbox_user_idemkey"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # 建议类型（开放集合，服务层校验）：review_due / resource_recommend / goal_nudge /
    # community_digest / system_hint 等，随 AG-P3 各条目扩充
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 来源域：auxilio / exam / community / github / scheduler
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 可解释性：为什么给出该建议（验收标准：展示理由，不伪装为确定事实）
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 模型/规则置信度 0.0~1.0；规则产生的建议可为 NULL
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 预计耗时（分钟）
    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 附带数据（跳转目标、证据引用等），不出现在列表过滤逻辑中
    payload: Mapped[Optional[dict]] = mapped_column(JSONDict, nullable=True)
    # 状态机：pending -> accepted | dismissed | snoozed；snoozed 到期自动回 pending
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    snoozed_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return (
            f"<AgentInboxItem(id={self.id}, user_id={self.user_id}, "
            f"type='{self.type}', status='{self.status}')>"
        )
