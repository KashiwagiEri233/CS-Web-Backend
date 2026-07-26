"""操作审计日志模型：记录敏感管理操作。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime as _DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class AuditLog(Base):
    """审计日志：谁在何时对什么资源做了什么。"""

    __tablename__ = "audit_logs"

    # 索引对齐 list_logs 的查询形态：「按某列过滤 + 恒定 ORDER BY created_at DESC」。
    # 单列索引只能加速过滤，排序仍需回表重排；(过滤列, created_at) 复合索引可以同时
    # 吃掉过滤与排序，索引数量还比原来的 5 个孤立单列索引更少。
    __table_args__ = (
        Index("idx_audit_action_created", "action", "created_at"),
        Index("idx_audit_resource_type_created", "resource_type", "created_at"),
        Index("idx_audit_resource_id_created", "resource_id", "created_at"),
        Index("idx_audit_actor_created", "actor_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actor_username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONDict, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, nullable=False, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action={self.action!r}, "
            f"resource={self.resource_type}:{self.resource_id})>"
        )
