"""Agent 每周复盘 API（AG-P3-04）：工作台读路径，按周去重，失败静默降级。"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_active_user
from app.dependencies_services import get_agent_weekly_review_service
from app.models.user import User
from app.schemas.agent_weekly_review import AgentWeeklyReviewOut
from app.services.agent_weekly_review_service import AgentWeeklyReviewService

router = APIRouter()


@router.get("", response_model=AgentWeeklyReviewOut)
async def get_weekly_review(
    service: AgentWeeklyReviewService = Depends(get_agent_weekly_review_service),
    current_user: User = Depends(get_current_active_user),
    week_start: Optional[date_type] = Query(
        default=None, alias="weekStart", description="周起始日（周一，默认本周）"
    ),
) -> Any:
    """我的每周复盘（当周不存在则生成；单节失败不影响读取）。"""
    return await service.get_or_generate(current_user.id, week_start)
