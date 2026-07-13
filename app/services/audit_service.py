"""审计服务：best-effort 写入 + 查询。

写入默认使用独立会话，避免与业务请求会话互相 rollback 污染。
查询使用构造注入的请求级 db（只读）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.loguru_logger import get_logger
from app.core.timezone import utc_to_local
from app.models.audit_log import AuditLog

logger = get_logger("audit")


class AuditService:
    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        actor_id: Optional[int] = None,
        actor_username: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        commit: bool = True,
        use_shared_session: bool = False,
    ) -> Optional[AuditLog]:
        """记录一条审计日志（默认独立会话，失败不阻断业务）。"""
        try:
            if use_shared_session and self.db is not None:
                return await self._write(
                    self.db,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    actor_id=actor_id,
                    actor_username=actor_username,
                    detail=detail,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    commit=commit,
                )

            from app.database import get_session

            async with get_session() as db:
                return await self._write(
                    db,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    actor_id=actor_id,
                    actor_username=actor_username,
                    detail=detail,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    commit=True,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"审计写入失败（已忽略）: {type(e).__name__}: {e}")
            return None

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
        """分页查询审计日志（需请求级 db）。"""
        db = self._require_db()
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

        total = int((await db.execute(count_stmt)).scalar_one())
        result = await db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def get_log(self, log_id: int) -> Optional[AuditLog]:
        """按 ID 获取审计日志。"""
        db = self._require_db()
        result = await db.execute(select(AuditLog).where(AuditLog.id == log_id))
        return result.scalar_one_or_none()

    @staticmethod
    def to_item_dict(row: AuditLog) -> Dict[str, Any]:
        """序列化为 API 字典（时间转本地展示）。"""
        created = row.created_at
        return {
            "id": row.id,
            "actor_id": row.actor_id,
            "actor_username": row.actor_username,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "detail": row.detail,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "created_at": utc_to_local(created).isoformat() if created else None,
        }

    def _require_db(self) -> AsyncSession:
        if self.db is None:
            raise RuntimeError("AuditService 查询需要注入 AsyncSession")
        return self.db

    async def _write(
        self,
        db: AsyncSession,
        *,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        actor_id: Optional[int],
        actor_username: Optional[str],
        detail: Optional[Dict[str, Any]],
        ip_address: Optional[str],
        user_agent: Optional[str],
        commit: bool,
    ) -> AuditLog:
        row = AuditLog(
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            actor_id=actor_id,
            actor_username=actor_username,
            detail=detail,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(row)
        await db.flush()
        if commit:
            await db.commit()
            await db.refresh(row)
        return row
