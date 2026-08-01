"""双因素认证模型：TOTP secret 加密存储 + 一次性备用码。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime as _DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class TwoFactorAuth(Base):
    """2FA 状态：secret 以 AES-256-GCM 加密存储；backup_codes 为哈希后的备用码列表。

    每用户一行（user_id 主键），删除用户时级联清理。
    """

    __tablename__ = "two_factor_auth"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # 加密后的 TOTP secret（iv:tag:cipher hex，见 app/core/totp_encryption.py）
    secret_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    # 哈希后的备用码列表（JSONB），验证通过即移除
    backup_codes: Mapped[list] = mapped_column(JSONDict, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return f"<TwoFactorAuth(user_id={self.user_id}, enabled={self.enabled})>"
