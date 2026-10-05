"""Agent 每日学习简报 API（AG-P3-03）：工作台读路径，按日去重，失败静默降级。"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_active_user
from app.dependencies_services import get_agent_briefing_service
from app.models.user import User
from app.schemas.agent_briefing import AgentBriefingOut
from app.services.agent_briefing_service import AgentBriefingService

router = APIRouter()


@router.get("", response_model=AgentBriefingOut)
async def get_briefing(
    service: AgentBriefingService = Depends(get_agent_briefing_service),
    current_user: User = Depends(get_current_active_user),
    brief_date: Optional[date_type] = Query(
        default=None, alias="date", description="简报日期（默认今天，配置时区）"
    ),
) -> Any:
    """我的每日学习简报（当日不存在则生成；生成失败不影响读取）。"""
    return await service.get_or_generate(current_user.id, brief_date)
