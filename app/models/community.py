"""社区 v2 统一模型（上游重构：论坛 + 博客合并为 community_* 系列）。

- community_categories：统一分类（论坛版块 + 博客分类）
- community_posts：统一内容（kind = topic | post）
- community_comments：统一评论（替代 forum_replies）
- community_reactions：多态点赞（target_type = post | comment）
- community_favorites：多态收藏
- community_post_views / community_mentions
- community_follows：用户关注
- community_reports：举报
- blog_series：文章系列（保留）

旧表（forum_* / blog_posts / blog_likes）保留在库中作数据迁移源，不再建模使用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime as _DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class CommunityCategory(Base):
    """统一分类：论坛版块 + 博客分类。"""

    __tablename__ = "community_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    post_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<CommunityCategory(id={self.id}, slug='{self.slug}')>"


class CommunityPost(Base):
    """统一内容：kind = topic | post。"""

    __tablename__ = "community_posts"

    __table_args__ = (
        Index("idx_community_posts_kind", "kind"),
        Index("idx_community_posts_category_id", "category_id"),
        Index("idx_community_posts_status", "status"),
        Index("idx_community_posts_author_id", "author_id"),
        Index("idx_community_posts_last_reply_at", "last_reply_at"),
        Index("idx_community_posts_is_pinned", "is_pinned"),
        Index("idx_community_posts_published_at", "published_at"),
        Index("idx_community_posts_series_id", "series_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # topic | post
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("community_categories.id", ondelete="CASCADE"),
        nullable=True,
    )
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reply_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_reply_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hidden_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    hidden_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    hidden_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 博客字段（kind = post 时使用）
    slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_image: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSONDict, nullable=True, default=list)
    series_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("blog_series.id", ondelete="SET NULL"), nullable=True
    )
    series_order: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    # 全文搜索向量（Phase 6 GIN 优化）：由数据库触发器维护（title + content_markdown）
    search_vector: Mapped[Optional[object]] = mapped_column(TSVECTOR, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return (
            f"<CommunityPost(id={self.id}, kind='{self.kind}', title='{self.title}')>"
        )


class CommunityComment(Base):
    """统一评论（替代论坛回复）。"""

    __tablename__ = "community_comments"

    __table_args__ = (
        Index("idx_community_comments_post_id", "post_id"),
        Index("idx_community_comments_parent_comment_id", "parent_comment_id"),
        Index("idx_community_comments_author_id", "author_id"),
        Index("idx_community_comments_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    parent_comment_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("community_comments.id", ondelete="CASCADE"), nullable=True
    )
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    hidden_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    hidden_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    hidden_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<CommunityComment(id={self.id}, post_id={self.post_id})>"


class CommunityReaction(Base):
    """多态点赞。"""

    __tablename__ = "community_reactions"

    __table_args__ = (
        Index("idx_community_reactions_target", "target_type", "target_id"),
        Index("idx_community_reactions_user_id", "user_id"),
        UniqueConstraint(
            "user_id", "target_type", "target_id", name="ux_community_reactions_unique"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # post | comment
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<CommunityReaction(id={self.id}, "
            f"target={self.target_type}:{self.target_id})>"
        )


class CommunityFavorite(Base):
    """多态收藏（目前仅 post）。"""

    __tablename__ = "community_favorites"

    __table_args__ = (
        Index("idx_community_favorites_user_id", "user_id"),
        Index("idx_community_favorites_target", "target_type", "target_id"),
        UniqueConstraint(
            "user_id", "target_type", "target_id", name="ux_community_favorites_unique"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<CommunityFavorite(id={self.id}, "
            f"target={self.target_type}:{self.target_id})>"
        )


class CommunityPostView(Base):
    """浏览去重：登录按 (post_id, user_id)，匿名按 (post_id, ip_hash)。"""

    __tablename__ = "community_post_views"

    __table_args__ = (
        Index("idx_community_post_views_post_id", "post_id"),
        Index(
            "idx_community_post_views_unique_user",
            "post_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "idx_community_post_views_unique_ip",
            "post_id",
            "ip_hash",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return f"<CommunityPostView(id={self.id}, post_id={self.post_id})>"


class CommunityMention(Base):
    """@提及。"""

    __tablename__ = "community_mentions"

    __table_args__ = (
        Index("idx_community_mentions_mentioned_user_id", "mentioned_user_id"),
        Index("idx_community_mentions_is_notified", "is_notified"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mentioned_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # post | comment
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_author_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<CommunityMention(id={self.id}, "
            f"mentioned_user_id={self.mentioned_user_id})>"
        )


class CommunityFollow(Base):
    """用户关注。"""

    __tablename__ = "community_follows"

    __table_args__ = (
        Index("idx_community_follows_follower", "follower_id"),
        Index("idx_community_follows_following", "following_id"),
        UniqueConstraint(
            "follower_id", "following_id", name="ux_community_follows_unique"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    follower_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    following_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<CommunityFollow(id={self.id}, {self.follower_id}->{self.following_id})>"
        )


class CommunityReport(Base):
    """举报：status = pending | resolved | dismissed。"""

    __tablename__ = "community_reports"

    __table_args__ = (
        Index("idx_community_reports_status", "status"),
        Index("idx_community_reports_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # post | comment
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    handled_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    handled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<CommunityReport(id={self.id}, "
            f"target={self.target_type}:{self.target_id})>"
        )
