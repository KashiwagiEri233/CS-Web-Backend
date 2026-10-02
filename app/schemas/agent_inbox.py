"""Agent 建议收件箱出入参（AG-P3-01）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import TZModel


class AgentInboxItemOut(TZModel):
    """建议收件箱出参。"""

    id: int
    user_id: int
    type: str
    source: str
    title: str
    reason: Optional[str] = None
    confidence: Optional[float] = None
    estimated_minutes: Optional[int] = None
    payload: Optional[dict[str, Any]] = None
    status: str
    snoozed_until: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class InboxStatusActionIn(BaseModel):
    """用户对建议的处理动作：accept / dismiss / snooze。

    model_config 显式声明（In 入参非 TZModel，不享受全局 from_attributes）。
    """

    model_config = ConfigDict(extra="forbid")

    action: str = Field(description="accept | dismiss | snooze")
    snooze_minutes: Optional[int] = Field(
        default=None, ge=1, le=60 * 24 * 7, description="snooze 时的延后分钟数"
    )
