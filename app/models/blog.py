"""博客模型：blog_posts / blog_series / blog_likes。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class BlogPost(Base):
    """博客文章：slug 唯一；status = draft | published | archived | deleted。"""

    __tablename__ = "blog_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="general", index=True
    )
    # 标签（JSON 数组）
    tags: Mapped[Optional[list]] = mapped_column(JSONDict, nullable=True, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    series_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("blog_series.id"), nullable=True
    )
    series_order: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return f"<BlogPost(id={self.id}, slug='{self.slug}', status='{self.status}')>"


class BlogSeries(Base):
    """文章系列：slug 唯一。"""

    __tablename__ = "blog_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return f"<BlogSeries(id={self.id}, slug='{self.slug}')>"


class BlogLike(Base):
    """博客点赞：(post_id, user_id) 唯一防止重复点赞。"""

    __tablename__ = "blog_likes"

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="ux_blog_likes_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("blog_posts.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<BlogLike(id={self.id}, post_id={self.post_id}, user_id={self.user_id})>"
        )
