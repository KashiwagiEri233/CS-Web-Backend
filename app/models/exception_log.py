"""
异常日志数据模型
定义异常日志记录的数据库表结构
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

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
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

# 所有时间列统一带时区：映射为 Postgres TIMESTAMP WITH TIME ZONE，
# 与代码库中 datetime.now(timezone.utc)（UTC aware）的约定对齐，
# 避免向无时区列写入 aware 时间（asyncpg DataError）以及读回后 naive/aware 混用比较报错。
DateTime = _DateTime(timezone=True)


class ExceptionLog(Base):
    """异常日志表"""

    __tablename__ = "exception_logs"

    id = Column(Integer, primary_key=True, index=True)
    traceback_id = Column(String(64), nullable=False, index=True, comment="异常跟踪ID")

    # 异常基本信息
    exception_type = Column(String(100), nullable=False, index=True, comment="异常类型")
    error_code = Column(String(100), nullable=True, index=True, comment="错误代码")
    exception_message = Column(Text, nullable=False, comment="异常消息")

    # HTTP相关信息
    status_code = Column(Integer, nullable=True, index=True, comment="HTTP状态码")
    method = Column(String(10), nullable=True, comment="HTTP方法")
    endpoint = Column(String(255), nullable=True, index=True, comment="请求端点")

    # 请求上下文信息
    request_id = Column(String(64), nullable=True, index=True, comment="请求ID")
    user_id = Column(String(64), nullable=True, index=True, comment="用户ID")
    ip_address = Column(String(45), nullable=True, comment="客户端IP地址")
    user_agent = Column(Text, nullable=True, comment="用户代理")

    # 异常详细信息
    details = Column(JSON, nullable=True, comment="异常详细信息")
    traceback = Column(Text, nullable=True, comment="异常堆栈")
    context = Column(JSON, nullable=True, comment="异常上下文信息")

    # 时间信息
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="创建时间",
    )

    # 处理状态
    is_resolved = Column(Boolean, default=False, nullable=False, comment="是否已解决")
    resolved_at = Column(DateTime, nullable=True, comment="解决时间")
    resolved_by = Column(String(64), nullable=True, comment="解决人")
    resolution_notes = Column(Text, nullable=True, comment="解决备注")

    # 严重程度
    severity = Column(
        String(20), default="medium", nullable=False, index=True, comment="严重程度"
    )
    priority = Column(
        String(20), default="normal", nullable=False, index=True, comment="优先级"
    )

    # 关联信息
    parent_exception_id = Column(
        Integer, ForeignKey("exception_logs.id"), nullable=True, comment="父异常ID"
    )
    related_incident_id = Column(
        String(64), nullable=True, index=True, comment="关联事件ID"
    )

    # 性能影响
    response_time_ms = Column(Float, nullable=True, comment="响应时间(毫秒)")

    # 索引
    __table_args__ = (
        Index("idx_exception_type_created", "exception_type", "created_at"),
        Index("idx_error_code_created", "error_code", "created_at"),
        Index("idx_status_code_created", "status_code", "created_at"),
        Index("idx_user_id_created", "user_id", "created_at"),
        Index("idx_traceback_id_user", "traceback_id", "user_id"),
        Index("idx_created_at_severity", "created_at", "severity"),
        Index("idx_is_resolved_created", "is_resolved", "created_at"),
    )

    # 关系
    parent_exception = relationship("ExceptionLog", remote_side=[id])

    def __repr__(self):
        return f"<ExceptionLog(id={self.id}, traceback_id={self.traceback_id}, exception_type={self.exception_type}, status_code={self.status_code})>"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
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


class ExceptionPattern(Base):
    """异常模式表"""

    __tablename__ = "exception_patterns"

    id = Column(Integer, primary_key=True, index=True)
    pattern_name = Column(
        String(100), nullable=False, unique=True, index=True, comment="模式名称"
    )
    pattern_type = Column(String(50), nullable=False, index=True, comment="模式类型")

    # 模式定义
    exception_type = Column(String(100), nullable=True, comment="异常类型")
    error_code = Column(String(100), nullable=True, comment="错误代码")
    endpoint_pattern = Column(String(255), nullable=True, comment="端点模式")
    user_id_pattern = Column(String(100), nullable=True, comment="用户ID模式")

    # 统计信息
    occurrence_count = Column(Integer, default=0, nullable=False, comment="出现次数")
    last_occurrence = Column(DateTime, nullable=True, comment="最后一次出现时间")

    # 时间信息
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="创建时间",
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="更新时间",
    )

    # 激活状态
    is_active = Column(Boolean, default=True, nullable=False, comment="是否激活")
    alert_threshold = Column(Integer, default=10, nullable=False, comment="告警阈值")

    def __repr__(self):
        return f"<ExceptionPattern(id={self.id}, pattern_name={self.pattern_name}, pattern_type={self.pattern_type})>"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "pattern_name": self.pattern_name,
            "pattern_type": self.pattern_type,
            "exception_type": self.exception_type,
            "error_code": self.error_code,
            "endpoint_pattern": self.endpoint_pattern,
            "user_id_pattern": self.user_id_pattern,
            "occurrence_count": self.occurrence_count,
            "last_occurrence": (
                self.last_occurrence.isoformat() if self.last_occurrence else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active,
            "alert_threshold": self.alert_threshold,
        }


class ExceptionAlert(Base):
    """异常告警表"""

    __tablename__ = "exception_alerts"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(
        String(64), nullable=False, unique=True, index=True, comment="告警ID"
    )

    # 告警基本信息
    alert_type = Column(String(50), nullable=False, index=True, comment="告警类型")
    severity = Column(
        String(20), default="medium", nullable=False, index=True, comment="严重程度"
    )
    title = Column(String(255), nullable=False, comment="告警标题")
    description = Column(Text, nullable=False, comment="告警描述")

    # 关联信息
    pattern_id = Column(
        Integer, ForeignKey("exception_patterns.id"), nullable=True, comment="模式ID"
    )
    exception_log_ids = Column(JSON, nullable=True, comment="相关异常日志ID列表")

    # 告警状态
    status = Column(
        String(20), default="open", nullable=False, index=True, comment="状态"
    )
    acknowledged_by = Column(String(64), nullable=True, comment="确认人")
    acknowledged_at = Column(DateTime, nullable=True, comment="确认时间")
    resolved_by = Column(String(64), nullable=True, comment="解决人")
    resolved_at = Column(DateTime, nullable=True, comment="解决时间")

    # 时间信息
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="创建时间",
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="更新时间",
    )

    # 通知信息
    notification_sent = Column(
        Boolean, default=False, nullable=False, comment="是否已发送通知"
    )
    notification_channels = Column(JSON, nullable=True, comment="通知渠道")

    def __repr__(self):
        return f"<ExceptionAlert(id={self.id}, alert_id={self.alert_id}, alert_type={self.alert_type}, status={self.status})>"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "pattern_id": self.pattern_id,
            "exception_log_ids": self.exception_log_ids,
            "status": self.status,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": (
                self.acknowledged_at.isoformat() if self.acknowledged_at else None
            ),
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "notification_sent": self.notification_sent,
            "notification_channels": self.notification_channels,
        }


class ExceptionMetrics(Base):
    """异常指标表"""

    __tablename__ = "exception_metrics"

    id = Column(Integer, primary_key=True, index=True)

    # 时间窗口
    time_window = Column(String(20), nullable=False, index=True, comment="时间窗口")
    window_start = Column(DateTime, nullable=False, index=True, comment="窗口开始时间")
    window_end = Column(DateTime, nullable=False, index=True, comment="窗口结束时间")

    # 总体指标
    total_exceptions = Column(Integer, default=0, nullable=False, comment="总异常数")
    unique_tracebacks = Column(
        Integer, default=0, nullable=False, comment="唯一异常跟踪数"
    )

    # 分类指标
    client_errors_4xx = Column(Integer, default=0, nullable=False, comment="4xx错误数")
    server_errors_5xx = Column(Integer, default=0, nullable=False, comment="5xx错误数")

    # 按异常类型分布
    application_exceptions = Column(
        Integer, default=0, nullable=False, comment="应用异常数"
    )
    http_exceptions = Column(Integer, default=0, nullable=False, comment="HTTP异常数")
    validation_exceptions = Column(
        Integer, default=0, nullable=False, comment="验证异常数"
    )
    database_exceptions = Column(
        Integer, default=0, nullable=False, comment="数据库异常数"
    )

    # 按用户分布
    exceptions_from_authenticated_users = Column(
        Integer, default=0, nullable=False, comment="认证用户异常数"
    )
    exceptions_from_anonymous_users = Column(
        Integer, default=0, nullable=False, comment="匿名用户异常数"
    )

    # 按端点分布
    top_endpoints = Column(JSON, nullable=True, comment="异常最多的端点")
    top_error_codes = Column(JSON, nullable=True, comment="最常见的错误代码")

    # 时间信息
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="创建时间",
    )

    def __repr__(self):
        return f"<ExceptionMetrics(id={self.id}, time_window={self.time_window}, total_exceptions={self.total_exceptions})>"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "time_window": self.time_window,
            "window_start": (
                self.window_start.isoformat() if self.window_start else None
            ),
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "total_exceptions": self.total_exceptions,
            "unique_tracebacks": self.unique_tracebacks,
            "client_errors_4xx": self.client_errors_4xx,
            "server_errors_5xx": self.server_errors_5xx,
            "application_exceptions": self.application_exceptions,
            "http_exceptions": self.http_exceptions,
            "validation_exceptions": self.validation_exceptions,
            "database_exceptions": self.database_exceptions,
            "exceptions_from_authenticated_users": self.exceptions_from_authenticated_users,
            "exceptions_from_anonymous_users": self.exceptions_from_anonymous_users,
            "top_endpoints": self.top_endpoints,
            "top_error_codes": self.top_error_codes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
