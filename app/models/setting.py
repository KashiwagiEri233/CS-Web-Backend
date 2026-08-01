"""系统设置模型：按 (module, key) 存储键值配置。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime as _DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class Setting(Base):
    """系统设置：module+key 唯一，value 存 JSON 序列化文本。"""

    __tablename__ = "settings"

    __table_args__ = (UniqueConstraint("module", "key", name="ux_settings_module_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return f"<Setting(id={self.id}, module='{self.module}', key='{self.key}')>"
