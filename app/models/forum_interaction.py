"""论坛互动模型：forum_likes / forum_favorites / forum_topic_views / forum_mentions。"""

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
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base

DateTime = _DateTime(timezone=True)


class ForumLike(Base):
    """点赞：(user_id, target_type, target_id) 唯一，target_type = topic | reply。"""

    __tablename__ = "forum_likes"

    __table_args__ = (
        Index("idx_forum_likes_target", "target_type", "target_id"),
        UniqueConstraint(
            "user_id", "target_type", "target_id", name="ux_forum_likes_unique"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<ForumLike(id={self.id}, user_id={self.user_id}, "
            f"target={self.target_type}:{self.target_id})>"
        )


class ForumFavorite(Base):
    """收藏：(user_id, topic_id) 唯一防止重复收藏。"""

    __tablename__ = "forum_favorites"

    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", name="ux_forum_favorites_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    topic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forum_topics.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<ForumFavorite(id={self.id}, user_id={self.user_id}, "
            f"topic_id={self.topic_id})>"
        )


class ForumTopicView(Base):
    """主题浏览去重：登录用户按 (topic_id, user_id) 唯一，匿名按 (topic_id, ip_hash) 唯一。"""

    __tablename__ = "forum_topic_views"

    __table_args__ = (
        Index(
            "idx_forum_topic_views_unique_user",
            "topic_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "idx_forum_topic_views_unique_ip",
            "topic_id",
            "ip_hash",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forum_topics.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<ForumTopicView(id={self.id}, topic_id={self.topic_id}, "
            f"user_id={self.user_id})>"
        )


class ForumMention(Base):
    """@ 提及：source_type = topic | reply；is_notified 标记通知是否已发送。"""

    __tablename__ = "forum_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mentioned_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_author_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    is_notified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<ForumMention(id={self.id}, mentioned_user_id={self.mentioned_user_id})>"
        )
