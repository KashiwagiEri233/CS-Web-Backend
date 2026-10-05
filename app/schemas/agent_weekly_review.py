"""Agent 每周复盘出入参（AG-P3-04）。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.schemas.base import TZModel


class AgentWeeklyReviewOut(TZModel):
    """周复盘出参。"""

    id: int
    user_id: int
    week_start: date
    content: Optional[dict[str, Any]] = None
    status: str
    created_at: datetime
    updated_at: datetime
