"""Agent 每日学习简报出入参（AG-P3-03）。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.schemas.base import TZModel


class AgentBriefingOut(TZModel):
    """简报出参：分节内容 + 状态（failed 时前端静默降级）。"""

    id: int
    user_id: int
    brief_date: date
    content: Optional[dict[str, Any]] = None
    status: str
    created_at: datetime
    updated_at: datetime
