"""Agent 自动化规则出入参（AG-P3-02）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import TZModel


class AgentAutomationRuleOut(TZModel):
    """规则出参。"""

    id: int
    user_id: int
    name: str
    trigger_type: str
    condition: Optional[dict[str, Any]] = None
    action_type: str
    action_payload: Optional[dict[str, Any]] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    cooldown_minutes: int
    max_per_hour: int
    enabled: bool
    last_fired_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AgentRuleInput(BaseModel):
    """创建入参（enabled 固定 False，创建后由用户启停）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    trigger_type: str = Field(max_length=32)
    condition: Optional[dict[str, Any]] = None
    action_payload: Optional[dict[str, Any]] = None
    quiet_hours_start: Optional[str] = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    quiet_hours_end: Optional[str] = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    cooldown_minutes: int = Field(default=240, ge=0, le=60 * 24 * 7)
    max_per_hour: int = Field(default=3, ge=1, le=60)


class AgentRuleUpdateIn(BaseModel):
    """更新入参（部分字段可选；action_type 不可变）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    trigger_type: Optional[str] = Field(default=None, max_length=32)
    condition: Optional[dict[str, Any]] = None
    action_payload: Optional[dict[str, Any]] = None
    quiet_hours_start: Optional[str] = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    quiet_hours_end: Optional[str] = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    cooldown_minutes: Optional[int] = Field(default=None, ge=0, le=60 * 24 * 7)
    max_per_hour: Optional[int] = Field(default=None, ge=1, le=60)


class AgentRuleEnableIn(BaseModel):
    """启停入参。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
