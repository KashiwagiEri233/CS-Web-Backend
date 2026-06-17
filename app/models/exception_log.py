"""
异常日志数据模型
只保留 ExceptionLog（记录 + 查询 + 解决）。
模式识别/告警/指标已移除——如需 APM 能力建议接入专业工具（Sentry/Datadog）。
"""

from datetime import datetime, timezone
from typing import Dict, Any

from sqlalchemy import (
    Column,
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
from sqlalchemy.orm import relationship

from app.database import Base

DateTime = _DateTime(timezone=True)


class ExceptionLog(Base):
    """异常日志表"""

    __tablename__ = "exception_logs"

    id = Column(Integer, primary_key=True, index=True)
    traceback_id = Column(String(64), nullable=False, index=True, comment="异常跟踪ID")

    exception_type = Column(String(100), nullable=False, index=True, comment="异常类型")
    error_code = Column(String(100), nullable=True, index=True, comment="错误代码")
    exception_message = Column(Text, nullable=False, comment="异常消息")

    status_code = Column(Integer, nullable=True, index=True, comment="HTTP状态码")
    method = Column(String(10), nullable=True, comment="HTTP方法")
    endpoint = Column(String(255), nullable=True, index=True, comment="请求端点")

    request_id = Column(String(64), nullable=True, index=True, comment="请求ID")
    user_id = Column(String(64), nullable=True, index=True, comment="用户ID")
    ip_address = Column(String(45), nullable=True, comment="客户端IP地址")
    user_agent = Column(Text, nullable=True, comment="用户代理")

    details = Column(JSON, nullable=True, comment="异常详细信息")
    traceback = Column(Text, nullable=True, comment="异常堆栈")
    context = Column(JSON, nullable=True, comment="异常上下文信息")

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="创建时间",
    )

    is_resolved = Column(Boolean, default=False, nullable=False, comment="是否已解决")
    resolved_at = Column(DateTime, nullable=True, comment="解决时间")
    resolved_by = Column(String(64), nullable=True, comment="解决人")
    resolution_notes = Column(Text, nullable=True, comment="解决备注")

    severity = Column(
        String(20), default="medium", nullable=False, index=True, comment="严重程度"
    )
    priority = Column(
        String(20), default="normal", nullable=False, index=True, comment="优先级"
    )

    parent_exception_id = Column(
        Integer, ForeignKey("exception_logs.id"), nullable=True, comment="父异常ID"
    )
    related_incident_id = Column(
        String(64), nullable=True, index=True, comment="关联事件ID"
    )

    response_time_ms = Column(Float, nullable=True, comment="响应时间(毫秒)")

    __table_args__ = (
        Index("idx_exception_type_created", "exception_type", "created_at"),
        Index("idx_error_code_created", "error_code", "created_at"),
        Index("idx_status_code_created", "status_code", "created_at"),
        Index("idx_user_id_created", "user_id", "created_at"),
        Index("idx_traceback_id_user", "traceback_id", "user_id"),
        Index("idx_created_at_severity", "created_at", "severity"),
        Index("idx_is_resolved_created", "is_resolved", "created_at"),
    )

    parent_exception = relationship("ExceptionLog", remote_side=[id])

    def __repr__(self):
        return f"<ExceptionLog(id={self.id}, traceback_id={self.traceback_id}, exception_type={self.exception_type}, status_code={self.status_code})>"

    def to_dict(self) -> Dict[str, Any]:
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
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_resolved": self.is_resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_notes": self.resolution_notes,
            "severity": self.severity,
            "priority": self.priority,
            "parent_exception_id": self.parent_exception_id,
            "related_incident_id": self.related_incident_id,
            "response_time_ms": self.response_time_ms,
        }
