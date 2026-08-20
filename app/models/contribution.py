"""贡献热力图缓存模型：contribution_cache（GitHub / LeetCode 按年缓存）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class ContributionCache(Base):
    """第三方平台贡献数据缓存（user_id + platform + year 唯一）。"""

    __tablename__ = "contribution_cache"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "platform", "year", name="uq_contribution_user_platform_year"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default="github")
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)
    # [{date: "YYYY-MM-DD", count: N}, ...]
    data: Mapped[Optional[list]] = mapped_column(JSONDict, nullable=True, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<ContributionCache({self.platform}/{self.username}/{self.year})>"
