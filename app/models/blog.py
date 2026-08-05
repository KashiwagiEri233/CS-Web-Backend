"""博客系列模型：blog_series（v2 社区博客系列）。

注：旧 ``blog_posts`` / ``blog_likes`` 表已并入 community v2 统一表，
其 ORM 映射于迁移完成后移除（详见 alembic 迁移 c8d9e0f1a2b3 的 Phase 6 说明）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime as _DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class BlogSeries(Base):
    """文章系列：slug 唯一。"""

    __tablename__ = "blog_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return f"<BlogSeries(id={self.id}, slug='{self.slug}')>"
