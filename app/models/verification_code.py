"""邮箱验证码模型：注册 / 找回密码的 HMAC 验证码存储。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime as _DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class VerificationCode(Base):
    """邮箱验证码：存 code_hash（不存明文）；used 标记是否已消费。"""

    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<VerificationCode(id={self.id}, email='{self.email}', used={self.used})>"
        )
