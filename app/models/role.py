from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.models.permission import Permission
    from app.models.user import User

from sqlalchemy import (
    Boolean,
    Column,
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.database import Base

# 带时区的 DateTime（Postgres TIMESTAMP WITH TIME ZONE），与 UTC aware 约定对齐
DateTime = _DateTime(timezone=True)

# 角色权限关联表
# 多对多关联表保持 Table + Column 写法（SQLAlchemy 2.0 推荐做法）；
# mapped_column 只用于 ORM 类属性，不能传给 Table()。
# permission_id 单独建索引：理由同 user_roles.role_id——复合主键无法加速反查
# （get_role_ids_by_permission / 鉴权 join）。
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
    Column(
        "permission_id",
        Integer,
        ForeignKey("permissions.id"),
        primary_key=True,
        index=True,
    ),
)


class Role(Base):
    """角色：RBAC 核心实体。

    display_name/is_system/sort_order 为前后端分离迁移（子阶段 2.5）新增字段，
    对齐前端 admin 角色管理 UI 的展示需求。
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    # 角色展示名（如「内容审核员」）；为空时回退 name
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # 系统内置角色（种子数据创建）：禁止删除
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    # 关联关系
    users: Mapped[List["User"]] = relationship(
        "User", secondary="user_roles", back_populates="roles"
    )
    permissions: Mapped[List["Permission"]] = relationship(
        "Permission", secondary=role_permissions, back_populates="roles"
    )

    def __repr__(self):
        return f"<Role(id={self.id}, name='{self.name}')>"
