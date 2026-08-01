"""社区仓储：论坛 / 博客 / 成员查询。

论坛搜索说明（Phase 4 迁移）：前端用 SQLite FTS5，本实现用关键词 ILIKE 等价查询
（关键词 AND 语义，标题+内容），GIN tsvector 全文索引列入 Phase 6 优化项。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.blog import BlogLike, BlogPost, BlogSeries
from app.models.forum import ForumCategory, ForumReply, ForumTopic
from app.models.forum_interaction import (
    ForumFavorite,
    ForumLike,
    ForumMention,
    ForumTopicView,
)
from app.models.user import User


class ForumCategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[ForumCategory]:
        stmt = select(ForumCategory).order_by(
            ForumCategory.sort_order.asc(), ForumCategory.created_at.asc()
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_slug(self, slug: str) -> Optional[ForumCategory]:
        stmt = select(ForumCategory).where(ForumCategory.slug == slug)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def get_by_id(self, category_id: int) -> Optional[ForumCategory]:
        return await self.db.get(ForumCategory, category_id)

    async def create(self, data: dict) -> ForumCategory:
        obj = ForumCategory(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, category: ForumCategory, data: dict) -> None:
        for key, value in data.items():
            setattr(category, key, value)

    async def delete(self, category_id: int) -> bool:
        obj = await self.get_by_id(category_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def adjust_counts(
        self, category_id: int, topic_delta: int, post_delta: int
    ) -> None:
        """反范式计数调整（topic_count / post_count）。"""
        stmt = (
            update(ForumCategory)
            .where(ForumCategory.id == category_id)
            .values(
                topic_count=func.max(ForumCategory.topic_count + topic_delta, 0),
                post_count=func.max(ForumCategory.post_count + post_delta, 0),
                updated_at=now_utc(),
            )
        )
        await self.db.execute(stmt)


class ForumTopicRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_topics(
        self,
        *,
        category_id: Optional[int] = None,
        search: Optional[str] = None,
        status: Optional[str] = None,
        include_hidden: bool = False,
        author_id: Optional[int] = None,
        sort: str = "latest",
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[ForumTopic], int]:
        conditions: list = []
        if include_hidden:
            conditions.append(ForumTopic.status.in_(["published", "hidden"]))
        elif status:
            conditions.append(ForumTopic.status == status)
        else:
            conditions.append(ForumTopic.status == "published")
        if category_id:
            conditions.append(ForumTopic.category_id == category_id)
        if author_id:
            conditions.append(ForumTopic.author_id == author_id)
        if search and search.strip():
            conditions.append(
                _keyword_condition(
                    ForumTopic.title, ForumTopic.content_markdown, search
                )
            )

        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(ForumTopic).where(*conditions)
                )
            ).scalar_one()
        )
        order = {
            "hot": (
                ForumTopic.is_pinned.desc(),
                ForumTopic.reply_count.desc(),
                ForumTopic.like_count.desc(),
            ),
            "top": (
                ForumTopic.is_pinned.desc(),
                ForumTopic.like_count.desc(),
                ForumTopic.view_count.desc(),
            ),
            "latest": (
                ForumTopic.is_pinned.desc(),
                ForumTopic.last_reply_at.is_(None),
                ForumTopic.last_reply_at.desc(),
                ForumTopic.created_at.desc(),
            ),
        }.get(sort, ())
        stmt = (
            select(ForumTopic)
            .where(*conditions)
            .order_by(*order)
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def list_favorites(
        self, user_id: int, skip: int, limit: int
    ) -> tuple[list[ForumTopic], int]:
        stmt = (
            select(ForumTopic)
            .join(ForumFavorite, ForumFavorite.topic_id == ForumTopic.id)
            .where(
                ForumFavorite.user_id == user_id,
                ForumTopic.status == "published",
            )
            .order_by(ForumFavorite.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        total = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(ForumFavorite)
                    .where(ForumFavorite.user_id == user_id)
                )
            ).scalar_one()
        )
        return list(rows.scalars().all()), total

    async def get_by_id(self, topic_id: int) -> Optional[ForumTopic]:
        return await self.db.get(ForumTopic, topic_id)

    async def create(self, data: dict) -> ForumTopic:
        obj = ForumTopic(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, topic: ForumTopic, data: dict) -> None:
        for key, value in data.items():
            setattr(topic, key, value)

    async def set_status(self, topic_id: int, status: str) -> None:
        await self.db.execute(
            update(ForumTopic)
            .where(ForumTopic.id == topic_id)
            .values(status=status, updated_at=now_utc())
        )

    async def toggle_pinned(self, topic_id: int, pinned: bool) -> None:
        await self.db.execute(
            update(ForumTopic).where(ForumTopic.id == topic_id).values(is_pinned=pinned)
        )

    async def toggle_featured(self, topic_id: int, featured: bool) -> None:
        await self.db.execute(
            update(ForumTopic)
            .where(ForumTopic.id == topic_id)
            .values(is_featured=featured)
        )

    async def hard_delete(self, topic_id: int) -> None:
        await self.db.execute(
            update(ForumTopic).where(ForumTopic.id == topic_id).values(status="deleted")
        )

    async def increment_view(self, topic_id: int) -> None:
        await self.db.execute(
            update(ForumTopic)
            .where(ForumTopic.id == topic_id)
            .values(view_count=ForumTopic.view_count + 1)
        )


class ForumReplyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_topic(
        self, topic_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[ForumReply], int]:
        conditions = [
            ForumReply.topic_id == topic_id,
            ForumReply.status == "published",
            ForumReply.parent_reply_id.is_(None),
        ]
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(ForumReply).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = (
            select(ForumReply)
            .where(*conditions)
            .order_by(ForumReply.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def list_nested(self, parent_reply_id: int) -> list[ForumReply]:
        stmt = (
            select(ForumReply)
            .where(
                ForumReply.parent_reply_id == parent_reply_id,
                ForumReply.status == "published",
            )
            .order_by(ForumReply.created_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_for_author(
        self, author_id: int, *, skip: int, limit: int
    ) -> tuple[list[ForumReply], int]:
        conditions = [
            ForumReply.author_id == author_id,
            ForumReply.status == "published",
        ]
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(ForumReply).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = (
            select(ForumReply)
            .where(*conditions)
            .order_by(ForumReply.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, reply_id: int) -> Optional[ForumReply]:
        return await self.db.get(ForumReply, reply_id)

    async def create(self, data: dict) -> ForumReply:
        obj = ForumReply(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, reply: ForumReply, content_markdown: str) -> None:
        reply.content_markdown = content_markdown
        reply.updated_at = now_utc()

    async def set_status(self, reply_id: int, status: str) -> None:
        await self.db.execute(
            update(ForumReply)
            .where(ForumReply.id == reply_id)
            .values(status=status, updated_at=now_utc())
        )

    async def hard_delete(self, reply_id: int) -> None:
        await self.db.execute(
            update(ForumReply).where(ForumReply.id == reply_id).values(status="deleted")
        )


class ForumInteractionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_like(
        self, user_id: int, target_type: str, target_id: int
    ) -> Optional[ForumLike]:
        stmt = select(ForumLike).where(
            ForumLike.user_id == user_id,
            ForumLike.target_type == target_type,
            ForumLike.target_id == target_id,
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def add_like(self, user_id: int, target_type: str, target_id: int) -> None:
        self.db.add(
            ForumLike(user_id=user_id, target_type=target_type, target_id=target_id)
        )
        await self.db.flush()

    async def remove_like(self, like: ForumLike) -> None:
        await self.db.delete(like)

    async def adjust_like_count(self, table, target_id: int, delta: int) -> int:
        result = await self.db.execute(
            update(table)
            .where(table.id == target_id)
            .values(like_count=func.max(table.like_count + delta, 0))
            .returning(table.like_count)
        )
        return int((result.scalar() or 0))

    async def get_favorite(
        self, user_id: int, topic_id: int
    ) -> Optional[ForumFavorite]:
        stmt = select(ForumFavorite).where(
            ForumFavorite.user_id == user_id, ForumFavorite.topic_id == topic_id
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def add_favorite(self, user_id: int, topic_id: int) -> None:
        self.db.add(ForumFavorite(user_id=user_id, topic_id=topic_id))
        await self.db.flush()

    async def remove_favorite(self, favorite: ForumFavorite) -> None:
        await self.db.delete(favorite)

    async def adjust_favorite_count(self, topic_id: int, delta: int) -> int:
        result = await self.db.execute(
            update(ForumTopic)
            .where(ForumTopic.id == topic_id)
            .values(favorite_count=func.max(ForumTopic.favorite_count + delta, 0))
            .returning(ForumTopic.favorite_count)
        )
        return int((result.scalar() or 0))

    async def has_viewed_recently(
        self, topic_id: int, *, user_id: Optional[int], ip_hash: Optional[str], since
    ) -> bool:
        if user_id:
            stmt = select(ForumTopicView.id).where(
                ForumTopicView.topic_id == topic_id,
                ForumTopicView.user_id == user_id,
                ForumTopicView.viewed_at >= since,
            )
        elif ip_hash:
            stmt = select(ForumTopicView.id).where(
                ForumTopicView.topic_id == topic_id,
                ForumTopicView.user_id.is_(None),
                ForumTopicView.ip_hash == ip_hash,
                ForumTopicView.viewed_at >= since,
            )
        else:
            return False
        rows = await self.db.execute(stmt.limit(1))
        return rows.scalar_one_or_none() is not None

    async def add_view(
        self, topic_id: int, *, user_id: Optional[int], ip_hash: Optional[str]
    ) -> None:
        self.db.add(ForumTopicView(topic_id=topic_id, user_id=user_id, ip_hash=ip_hash))
        await self.db.flush()

    async def create_mentions(self, mentions: list[dict]) -> None:
        for m in mentions:
            self.db.add(ForumMention(**m))
        await self.db.flush()

    async def list_mentions(self, user_id: int, limit: int = 20) -> list[ForumMention]:
        stmt = (
            select(ForumMention)
            .where(ForumMention.mentioned_user_id == user_id)
            .order_by(ForumMention.created_at.desc())
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())


class BlogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_posts(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        author_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[BlogPost], int]:
        conditions = []
        if status:
            conditions.append(BlogPost.status == status)
        if category:
            conditions.append(BlogPost.category == category)
        if author_id:
            conditions.append(BlogPost.author_id == author_id)
        if search and search.strip():
            conditions.append(
                _keyword_condition(BlogPost.title, BlogPost.excerpt, search)
            )
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(BlogPost).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = (
            select(BlogPost)
            .where(*conditions)
            .order_by(BlogPost.published_at.desc(), BlogPost.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_slug(self, slug: str) -> Optional[BlogPost]:
        stmt = select(BlogPost).where(BlogPost.slug == slug)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def get_by_id(self, post_id: int) -> Optional[BlogPost]:
        return await self.db.get(BlogPost, post_id)

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(BlogPost.id).where(BlogPost.slug == slug).limit(1)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none() is not None

    async def create(self, data: dict) -> BlogPost:
        obj = BlogPost(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, post: BlogPost, data: dict) -> None:
        for key, value in data.items():
            setattr(post, key, value)

    async def increment_view(self, post_id: int) -> None:
        await self.db.execute(
            update(BlogPost)
            .where(BlogPost.id == post_id)
            .values(view_count=BlogPost.view_count + 1)
        )

    async def list_series(self) -> list[BlogSeries]:
        stmt = select(BlogSeries).order_by(BlogSeries.created_at.desc())
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_series(self, series_id: int) -> Optional[BlogSeries]:
        return await self.db.get(BlogSeries, series_id)

    async def create_series(self, data: dict) -> BlogSeries:
        obj = BlogSeries(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def series_slug_exists(self, slug: str) -> bool:
        stmt = select(BlogSeries.id).where(BlogSeries.slug == slug).limit(1)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none() is not None

    async def delete_series(self, series_id: int) -> bool:
        obj = await self.get_series(series_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def get_like(self, post_id: int, user_id: int) -> Optional[BlogLike]:
        stmt = select(BlogLike).where(
            BlogLike.post_id == post_id, BlogLike.user_id == user_id
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def add_like(self, post_id: int, user_id: int) -> None:
        self.db.add(BlogLike(post_id=post_id, user_id=user_id))
        await self.db.flush()

    async def remove_like(self, like: BlogLike) -> None:
        await self.db.delete(like)

    async def adjust_post_like_count(self, post_id: int, delta: int) -> int:
        result = await self.db.execute(
            update(BlogPost)
            .where(BlogPost.id == post_id)
            .values(like_count=func.max(BlogPost.like_count + delta, 0))
            .returning(BlogPost.like_count)
        )
        return int((result.scalar() or 0))

    async def increment_topic_reply_count(self, topic_id: int) -> None:
        await self.db.execute(
            update(ForumTopic)
            .where(ForumTopic.id == topic_id)
            .values(reply_count=ForumTopic.reply_count + 1)
        )


class MemberRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self, tag: Optional[str] = None) -> list[User]:
        stmt = select(User).where(User.is_active.is_(True), User.deleted_at.is_(None))
        if tag and tag.strip():
            stmt = stmt.where(User.tech_tags.contains(f'"{tag.strip()}"'))
        stmt = stmt.order_by(User.display_name.asc(), User.id.asc())
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_all_tech_tags(self) -> list[str]:
        rows = await self.db.execute(
            select(User.tech_tags).where(
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.tech_tags.is_not(None),
            )
        )
        tag_set: set[str] = set()
        for (tags,) in rows.all():
            if isinstance(tags, list):
                tag_set.update(str(t) for t in tags)
        return sorted(tag_set)


def _keyword_condition(title_col, content_col, search: str) -> Any:
    """关键词搜索：分词后 AND 语义的 ILIKE 条件（FTS5 等价降级实现）。"""
    keywords = [kw for kw in search.strip().split() if kw]
    if not keywords:
        return None
    return and_all(
        [
            or_(title_col.ilike(f"%{kw}%"), content_col.ilike(f"%{kw}%"))
            for kw in keywords
        ]
    )


def and_all(conditions: Sequence):
    from sqlalchemy import and_

    return and_(*conditions)
