from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.models.role import Role

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
from app.models.types import JSONDict

# 带时区的 DateTime（Postgres TIMESTAMP WITH TIME ZONE），与 UTC aware 约定对齐
DateTime = _DateTime(timezone=True)

# 用户角色关联表
# 多对多关联表保持 Table + Column 写法（SQLAlchemy 2.0 推荐做法）；
# mapped_column 只用于 ORM 类属性，不能传给 Table()。
# role_id 单独建索引：复合主键 (user_id, role_id) 只能加速按 user_id 的查询，
# 按 role_id 反查（get_user_ids_by_role / 鉴权 join）会退化成顺序扫描。
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True, index=True),
)


class User(Base):
    """用户：认证字段（框架）+ 业务资料字段（前后端分离迁移合并）。"""

    __tablename__ = "users"

    # 主键不加 index=True：PostgreSQL 已为主键自动建唯一索引，再加会多出一个
    # 完全冗余的 ix_users_id，只增加写放大和磁盘占用。（其余模型同理）
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    # 改密时间：用于让改密前签发的 access token 立即失效（JWT 内 pwd_at 对比）
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, default=None
    )
    # 软删除时间；非空表示已删除，列表/鉴权默认排除
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    # ---- 业务资料字段（迁移自前端 users 表）----
    # 展示名：前端 display_name；无值时回退 username
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # 头像类型：initial（预设初始头像）| custom（自定义上传）| github（OAuth 头像）
    avatar_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="initial"
    )
    github_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    github_id: Mapped[Optional[str]] = mapped_column(
        String(50), unique=True, index=True, nullable=True
    )
    # 技术方向标签（JSON 数组），如 ["web", "ai"]
    tech_tags: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )

    # 关联关系
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary=user_roles, back_populates="users"
    )

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}')>"
