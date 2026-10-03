"""Agent 建议收件箱 API（AG-P3-01）：用户级建议列表与处理动作。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_active_user
from app.dependencies_services import get_agent_inbox_service
from app.models.user import User
from app.schemas.agent_inbox import AgentInboxItemOut, InboxStatusActionIn
from app.schemas.pagination import PaginationParams
from app.services.agent_inbox_service import AgentInboxService

router = APIRouter()


@router.get("", response_model=list[AgentInboxItemOut])
async def list_inbox(
    service: AgentInboxService = Depends(get_agent_inbox_service),
    current_user: User = Depends(get_current_active_user),
    status: Optional[str] = Query(default=None, description="按状态过滤"),
    type: Optional[str] = Query(default=None, description="按建议类型过滤"),
    pagination: PaginationParams = Depends(),
) -> Any:
    """我的建议收件箱（读取时惰性回收 snooze 到期与过期项）。"""
    items, _total = await service.list_inbox(
        current_user,
        status=status,
        type=type,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return items


@router.patch("/{item_id}/status", response_model=AgentInboxItemOut)
async def update_inbox_status(
    item_id: int,
    body: InboxStatusActionIn,
    service: AgentInboxService = Depends(get_agent_inbox_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """处理建议：accept / dismiss / snooze（+snoozeMinutes）。"""
    return await service.update_status(
        current_user, item_id, body.action, body.snooze_minutes
    )
