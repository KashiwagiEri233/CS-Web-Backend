"""审计日志仓储：只负责 AuditLog 的写入与查询。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.base import dml_rowcount


class AuditLogRepository:
    """操作审计日志的数据访问层。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> AuditLog:
        """新增审计日志并 flush；事务由 service 管理。"""
        row = AuditLog(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_logs(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        actor_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[List[AuditLog], int]:
        """按条件分页查询审计日志。"""
        conditions = []
        if action:
            conditions.append(AuditLog.action == action)
        if resource_type:
            conditions.append(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            conditions.append(AuditLog.resource_id == str(resource_id))
        if actor_id is not None:
            conditions.append(AuditLog.actor_id == actor_id)
        if start_date is not None:
            conditions.append(AuditLog.created_at >= start_date)
        if end_date is not None:
            conditions.append(AuditLog.created_at <= end_date)

        count_stmt = select(func.count()).select_from(AuditLog)
        query = select(AuditLog).order_by(desc(AuditLog.created_at))
        if conditions:
            where = and_(*conditions)
            count_stmt = count_stmt.where(where)
            query = query.where(where)

        total = int((await self.db.execute(count_stmt)).scalar_one())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def get_by_id(self, log_id: int) -> Optional[AuditLog]:
        """按 ID 查询单条审计日志。"""
        result = await self.db.execute(select(AuditLog).where(AuditLog.id == log_id))
        return result.scalar_one_or_none()

    async def delete(self, log: AuditLog) -> None:
        """删除单条日志。调用方负责 commit。"""
        await self.db.delete(log)

    async def delete_before(self, before: datetime) -> int:
        """批量删除早于指定时间的日志，返回删除行数。"""
        result = await self.db.execute(
            delete(AuditLog).where(AuditLog.created_at < before)
        )
        return dml_rowcount(result)
