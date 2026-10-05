"""Agent 自动化规则仓储（AG-P3-02）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_automation import AgentAutomationRule


class AgentAutomationRuleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, rule_id: int) -> Optional[AgentAutomationRule]:
        return await self.db.get(AgentAutomationRule, rule_id)

    async def list_for_user(
        self,
        user_id: int,
        *,
        enabled: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentAutomationRule], int]:
        base = select(AgentAutomationRule).where(AgentAutomationRule.user_id == user_id)
        if enabled is not None:
            base = base.where(AgentAutomationRule.enabled == enabled)
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        stmt = (
            base.order_by(AgentAutomationRule.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, int(total)

    async def list_enabled_all(self) -> list[AgentAutomationRule]:
        """全部启用的规则（触发引擎 cron 扫描入口，跨用户）。"""
        stmt = select(AgentAutomationRule).where(AgentAutomationRule.enabled.is_(True))
        return list((await self.db.execute(stmt)).scalars().all())

    async def create(self, data: dict) -> AgentAutomationRule:
        obj = AgentAutomationRule(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def count_fired_since(self, rule_id: int, since: datetime) -> int:
        """该规则自 since 以来被放行的次数（每小时频次水位判定）。

        依据收件箱建议的幂等键前缀 `rule:{rule_id}:` 统计（与 AG-P3-01 的
        idempotency_key 约定联动），避免在规则表上另行记流水的膨胀。
        """
        from app.models.agent_inbox import AgentInboxItem

        prefix = f"rule:{rule_id}:"
        stmt = (
            select(func.count())
            .select_from(AgentInboxItem)
            .where(
                AgentInboxItem.idempotency_key.like(prefix + "%"),
                AgentInboxItem.created_at >= since,
            )
        )
        return int((await self.db.execute(stmt)).scalar_one())
