"""
异常日志数据模型
只保留 ExceptionLog（记录 + 查询 + 解决）。
模式识别/告警/指标已移除——如需 APM 能力建议接入专业工具（Sentry/Datadog）。
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    String,
    Integer,
    DateTime as _DateTime,
    Text,
    Boolean,
    ForeignKey,
    Index,
    JSON,
    Float,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc, utc_to_local
from app.database import Base

DateTime = _DateTime(timezone=True)


class ExceptionLog(Base):
    """异常日志表"""

    __tablename__ = "exception_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    traceback_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="异常跟踪ID"
    )

    exception_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="异常类型"
    )
    error_code: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True, comment="错误代码"
    )
    exception_message: Mapped[str] = mapped_column(
        Text, nullable=False, comment="异常消息"
    )

    status_code: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True, comment="HTTP状态码"
    )
    method: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, comment="HTTP方法"
    )
    endpoint: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True, comment="请求端点"
    )

    request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True, comment="请求ID"
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True, comment="用户ID"
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, comment="客户端IP地址"
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="用户代理"
    )

    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="异常详细信息"
    )
    traceback: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="异常堆栈"
    )
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="异常上下文信息"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        nullable=False,
        index=True,
        comment="创建时间",
    )

    is_resolved: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否已解决"
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="解决时间"
    )
    resolved_by: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="解决人"
    )
    resolution_notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="解决备注"
    )

    severity: Mapped[str] = mapped_column(
        String(20), default="medium", nullable=False, index=True, comment="严重程度"
    )
    priority: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False, index=True, comment="优先级"
    )

    parent_exception_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("exception_logs.id"), nullable=True, comment="父异常ID"
    )
    related_incident_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True, comment="关联事件ID"
    )

    response_time_ms: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="响应时间(毫秒)"
    )

    __table_args__ = (
        Index("idx_exception_type_created", "exception_type", "created_at"),
        Index("idx_error_code_created", "error_code", "created_at"),
        Index("idx_status_code_created", "status_code", "created_at"),
        Index("idx_user_id_created", "user_id", "created_at"),
        Index("idx_traceback_id_user", "traceback_id", "user_id"),
        Index("idx_created_at_severity", "created_at", "severity"),
        Index("idx_is_resolved_created", "is_resolved", "created_at"),
    )

    parent_exception: Mapped[Optional["ExceptionLog"]] = relationship(
        "ExceptionLog", remote_side=[id]
    )

    def __repr__(self):
        return (
            "<ExceptionLog("
            f"id={self.id}, traceback_id={self.traceback_id}, "
            f"exception_type={self.exception_type}, status_code={self.status_code}"
            ")>"
        )

    def to_dict(self) -> Dict[str, Any]:
        created_at = utc_to_local(self.created_at)
        resolved_at = utc_to_local(self.resolved_at)
        return {
            "id": self.id,
            "traceback_id": self.traceback_id,
            "exception_type": self.exception_type,
            "error_code": self.error_code,
            "exception_message": self.exception_message,
            "status_code": self.status_code,
            "method": self.method,
            "endpoint": self.endpoint,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "details": self.details,
            "traceback": self.traceback,
            "context": self.context,
            "created_at": created_at.isoformat() if created_at else None,
            "is_resolved": self.is_resolved,
            "resolved_at": resolved_at.isoformat() if resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_notes": self.resolution_notes,
            "severity": self.severity,
            "priority": self.priority,
            "parent_exception_id": self.parent_exception_id,
            "related_incident_id": self.related_incident_id,
            "response_time_ms": self.response_time_ms,
        }
