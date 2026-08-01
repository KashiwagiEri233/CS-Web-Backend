from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.models.user import User

from sqlalchemy import (
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.database import Base

# 带时区的 DateTime（Postgres TIMESTAMP WITH TIME ZONE），与 UTC aware 约定对齐
DateTime = _DateTime(timezone=True)


class RefreshToken(Base):
    """持久化的 refresh token。

    设计要点：
    - 只存 token 的 sha256 哈希（token_hash），数据库泄漏不可直接复用。
    - family_id 标识同一次登录派生的刷新链；检测到 family 内已撤销 token 再次被使用时，
      整个 family 立即失效（refresh token rotation 的复用检测）。
    - revoked_at 软撤销；is_active 派生属性兼容旧代码风格。
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # sha256(refresh_token 明文)，长度固定 64（十六进制）。唯一索引防止重复。
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # 同一次登录派生的刷新链标识；同一 family 内的旧 token 再次被用 = 窃取/重放
    family_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    # 设备信息（会话管理展示用，Phase 1 迁移新增）
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", backref="refresh_tokens")

    @property
    def is_active(self) -> bool:
        """是否仍有效：未撤销且未过期。"""
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and now_utc() >= self.expires_at:
            return False
        return True

    def __repr__(self):
        return (
            f"<RefreshToken(id={self.id}, user_id={self.user_id}, "
            f"family_id={self.family_id!r}, active={self.is_active})>"
        )
