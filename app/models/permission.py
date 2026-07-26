from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.models.role import Role

from sqlalchemy import DateTime as _DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.database import Base

# 带时区的 DateTime（Postgres TIMESTAMP WITH TIME ZONE），与 UTC aware 约定对齐
DateTime = _DateTime(timezone=True)


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    resource: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 资源名称，如"user", "role"等
    action: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 操作名称，如"create", "read", "update", "delete"等
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    # 关联关系
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary="role_permissions", back_populates="permissions"
    )

    def __repr__(self):
        return (
            "<Permission("
            f"id={self.id}, name={self.name!r}, "
            f"resource={self.resource!r}, action={self.action!r}"
            ")>"
        )
