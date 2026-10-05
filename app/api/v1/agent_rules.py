"""Agent 自动化规则 API（AG-P3-02）：规则的 CRUD、启停与列表。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_active_user
from app.dependencies_services import get_agent_automation_service
from app.models.user import User
from app.schemas.agent_automation import (
    AgentAutomationRuleOut,
    AgentRuleEnableIn,
    AgentRuleInput,
    AgentRuleUpdateIn,
)
from app.schemas.pagination import PaginationParams
from app.services.agent_automation_service import AgentAutomationService

router = APIRouter()


@router.get("", response_model=list[AgentAutomationRuleOut])
async def list_rules(
    service: AgentAutomationService = Depends(get_agent_automation_service),
    current_user: User = Depends(get_current_active_user),
    enabled: Optional[bool] = Query(default=None, description="按启停过滤"),
    pagination: PaginationParams = Depends(),
) -> Any:
    """我的自动化规则列表。"""
    items, _total = await service.list_rules(
        current_user, enabled=enabled, skip=pagination.skip, limit=pagination.limit
    )
    return items


@router.post("", response_model=AgentAutomationRuleOut, status_code=201)
async def create_rule(
    body: AgentRuleInput,
    service: AgentAutomationService = Depends(get_agent_automation_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """创建规则（默认停用，创建后经启停接口打开）。"""
    return await service.create_rule(current_user, body.model_dump(exclude_unset=True))


@router.patch("/{rule_id}", response_model=AgentAutomationRuleOut)
async def update_rule(
    rule_id: int,
    body: AgentRuleUpdateIn,
    service: AgentAutomationService = Depends(get_agent_automation_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """更新规则（所有权校验；部分字段更新）。"""
    return await service.update_rule(
        current_user, rule_id, body.model_dump(exclude_unset=True)
    )


@router.patch("/{rule_id}/enabled", response_model=AgentAutomationRuleOut)
async def set_enabled(
    rule_id: int,
    body: AgentRuleEnableIn,
    service: AgentAutomationService = Depends(get_agent_automation_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """逐条启停。"""
    return await service.set_enabled(current_user, rule_id, body.enabled)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    service: AgentAutomationService = Depends(get_agent_automation_service),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """删除规则。"""
    await service.delete_rule(current_user, rule_id)
