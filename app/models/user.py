from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.models.role import Role

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime as _DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

# 带时区的 DateTime（Postgres TIMESTAMP WITH TIME ZONE），与 UTC aware 约定对齐
DateTime = _DateTime(timezone=True)

# 用户角色绑定表（带作用范围）。
# 以 id 为主键，允许同一用户对同一角色持有多个作用范围（如两个峰的峰主）。
# scope_type=own/all 时 scope_peak_id 必须为空；peak 时必须指向真实峰。
# 最小权限默认 own：旧代码若仅按 user/role 追加，不会意外获得全站范围。
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "user_id",
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column(
        "role_id",
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("scope_type", String(10), nullable=False, server_default="own"),
    Column(
        "scope_peak_id",
        BigInteger,
        ForeignKey("peaks.id"),
        nullable=True,
        index=True,
    ),
    Column("created_by", Integer, ForeignKey("users.id"), nullable=True),
    Column("created_at", DateTime, nullable=False, default=now_utc),
    Index(
        "uq_user_roles_scope_own_all",
        "user_id",
        "role_id",
        "scope_type",
        unique=True,
        postgresql_where=text("scope_type IN ('own', 'all')"),
    ),
    Index(
        "uq_user_roles_scope_peak",
        "user_id",
        "role_id",
        "scope_peak_id",
        unique=True,
        postgresql_where=text("scope_type = 'peak'"),
    ),
)


class UserRoleBinding(Base):
    """用户角色绑定：角色 + 作用范围（own / 指定峰 / all）。"""

    __table__ = user_roles

    __mapper_args__ = {"primary_key": [user_roles.c.id]}

    def __repr__(self) -> str:
        return (
            "<UserRoleBinding("
            f"user_id={self.user_id}, role_id={self.role_id}, "
            f"scope_type='{self.scope_type}', scope_peak_id={self.scope_peak_id}"
            ")>"
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
    # 授权版本：角色绑定或权限变更时递增；缓存键与受保护写校验使用该版本。
    authorization_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, server_default="1"
    )
    # 本人是否同意在钱包排行榜公开余额（默认关闭，避免迁移时自动公开资产）。
    show_wallet_on_leaderboard: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
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
    # 旧项目外接同步标识：官网用户与旧项目 users.sync_id 的稳定映射键，
    # 既作为幂等 upsert 依据，也作为 X-Acting-User-Id 的行为主体取值。
    # 由官网生成（UUID hex），存量用户由对账任务回填，故先允许为空。
    sync_id: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    # 技术方向标签（JSON 数组），如 ["web", "ai"]
    tech_tags: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    # 全文搜索向量（GIN 优化）：由数据库触发器维护（display_name + username）
    search_vector: Mapped[Optional[object]] = mapped_column(
        TSVECTOR, nullable=True, index=True
    )

    # 关联关系（selectin：async 会话下避免 lazy load MissingGreenlet）
    # user_roles 同时有 user_id 与 created_by 两条指向 users 的外键，
    # 必须显式指定 primaryjoin/secondaryjoin，避免多外键路径歧义。
    roles: Mapped[List["Role"]] = relationship(
        "Role",
        secondary=user_roles,
        primaryjoin="User.id == user_roles.c.user_id",
        secondaryjoin="Role.id == user_roles.c.role_id",
        back_populates="users",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}')>"
