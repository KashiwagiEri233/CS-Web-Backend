from datetime import datetime, timezone
from sqlalchemy import Column, DateTime as _DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base

# 带时区的 DateTime（Postgres TIMESTAMP WITH TIME ZONE），与 UTC aware 约定对齐
DateTime = _DateTime(timezone=True)


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    resource = Column(String(50), nullable=False)  # 资源名称，如"user", "role"等
    action = Column(
        String(50), nullable=False
    )  # 操作名称，如"create", "read", "update", "delete"等
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # 关联关系
    roles = relationship(
        "Role", secondary="role_permissions", back_populates="permissions"
    )

    def __repr__(self):
        return f"<Permission(id={self.id}, name='{self.name}', resource='{self.resource}', action='{self.action}')>"
