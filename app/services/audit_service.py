"""审计服务：best-effort 写入 + 查询。

写入默认使用独立会话，避免与业务请求会话互相 rollback 污染。
查询使用构造注入的请求级 db（只读）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.loguru_logger import get_logger
from app.core.timezone import utc_to_local
from app.models.audit_log import AuditLog
from app.repositories.audit_log_repo import AuditLogRepository

logger = get_logger("audit")


class AuditService:
    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.repo = AuditLogRepository(db) if db is not None else None

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
        strict: bool = False,
    ) -> Optional[AuditLog]:
        """记录审计日志。

        默认保持 best-effort 独立会话；敏感写操作应传
        ``use_shared_session=True, strict=True``，让业务变更与审计同事务提交。
        """
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
            if use_shared_session and self.db is not None:
                await self.db.rollback()
            if strict:
                raise
            logger.warning(f"审计写入失败（已忽略）: {type(e).__name__}: {e}")
            return None

    async def record_atomic(
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
    ) -> AuditLog:
        """在共享请求会话中提交业务变更和审计记录。

        路由层使用这个显式原子接口，避免重复组合 ``commit``、
        ``use_shared_session`` 和 ``strict`` 三个易错开关。
        """
        if self.db is None:
            raise RuntimeError("原子审计需要注入共享 AsyncSession")
        row = await self.record(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            actor_username=actor_username,
            detail=detail,
            ip_address=ip_address,
            user_agent=user_agent,
            commit=True,
            use_shared_session=True,
            strict=True,
        )
        if row is None:
            raise RuntimeError("原子审计写入未返回记录")
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
        """分页查询审计日志（需请求级 db）。"""
        return await self._require_repo().list_logs(
            skip=skip,
            limit=limit,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_log(self, log_id: int) -> Optional[AuditLog]:
        """按 ID 获取审计日志。"""
        return await self._require_repo().get_by_id(log_id)

    @staticmethod
    def to_item_dict(row: AuditLog) -> Dict[str, Any]:
        """序列化为 API 字典（时间转本地展示）。"""
        created = row.created_at
        local_created = utc_to_local(created)
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
            "created_at": local_created.isoformat() if local_created else None,
        }

    def _require_repo(self) -> AuditLogRepository:
        if self.repo is None:
            raise RuntimeError("AuditService 查询需要注入 AsyncSession")
        return self.repo

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
        repo = AuditLogRepository(db)
        row = await repo.create(
            {
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id is not None else None,
                "actor_id": actor_id,
                "actor_username": actor_username,
                "detail": detail,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
        )
        if commit:
            await db.commit()
            # 不做 refresh：会话是 expire_on_commit=False，提交后属性不会失效；
            # 主键由 repo.create 的 flush 回填、created_at 是 Python 侧默认值，
            # 没有任何服务端生成值需要回读。多一次 refresh 就是每条审计多一条 SELECT。
        return row
