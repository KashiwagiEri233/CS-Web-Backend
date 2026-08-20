"""用户 LLM 配置模型：llm_configs（用户自行接入 API Key，密钥 AES-256-GCM 加密存储）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class LlmConfig(Base):
    """用户级模型接入配置（每个用户一行）。api_key 加密存储，绝不回显明文。"""

    __tablename__ = "llm_configs"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="openai")
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    base_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="gpt-4o-mini")
    #: 用户级功能开关（默认开；false 时对应功能对该用户停用）
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trajectory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<LlmConfig(user={self.user_id}, {self.provider}, {self.model})>"
