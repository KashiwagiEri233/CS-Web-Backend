"""社区 v2 仓储：categories / posts / comments / reactions / favorites / views / mentions /
follows / reports / series。搜索基于 PostgreSQL 原生全文检索（GIN + tsvector，Phase 6 已落地）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional, Sequence

from sqlalchemy import func, select, text, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import VIEW_DEDUP_WINDOW_HOURS
from app.core.timezone import now_utc
from app.models.community_series import CommunitySeries
from app.models.community import (
    CommunityCategory,
    CommunityComment,
    CommunityFavorite,
    CommunityFollow,
    CommunityMention,
    CommunityPost,
    CommunityPostView,
    CommunityReaction,
    CommunityReport,
)
from app.models.user import User


class CommunityCategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[CommunityCategory]:
        stmt = select(CommunityCategory).order_by(
            CommunityCategory.sort_order.asc(), CommunityCategory.id.asc()
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_id(self, category_id: int) -> Optional[CommunityCategory]:
        return await self.db.get(CommunityCategory, category_id)

    async def get_by_slug(self, slug: str) -> Optional[CommunityCategory]:
        stmt = select(CommunityCategory).where(CommunityCategory.slug == slug)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def create(self, data: dict) -> CommunityCategory:
        obj = CommunityCategory(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, category: CommunityCategory, data: dict) -> None:
        for key, value in data.items():
            setattr(category, key, value)

    async def delete(self, category_id: int) -> bool:
        obj = await self.get_by_id(category_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True


class CommunityPostRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_posts(
        self,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        category_id: Optional[int] = None,
        category_slug: Optional[str] = None,
        tag: Optional[str] = None,
        series_id: Optional[int] = None,
        author_id: Optional[int] = None,
        search: Optional[str] = None,
        sort: str = "latest",
        include_hidden: bool = False,
        following_ids: Optional[Sequence[int]] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[CommunityPost], int]:
        conditions: list = []
        if kind:
            conditions.append(CommunityPost.kind == kind)
        if include_hidden:
            conditions.append(CommunityPost.status.in_(["published", "hidden"]))
        elif status:
            conditions.append(CommunityPost.status == status)
        else:
            conditions.append(CommunityPost.status == "published")
        if category_id:
            conditions.append(CommunityPost.category_id == category_id)
        if category_slug:
            conditions.append(
                CommunityPost.category_id.in_(
                    select(CommunityCategory.id).where(
                        CommunityCategory.slug == category_slug
                    )
                )
            )
        if tag and tag.strip():
            # ER-01 / ER-23：参数化 JSONB 包含查询。
            # 传入列表由 SQLAlchemy 绑定为参数，不再把用户输入拼进 SQL 字面量；
            # 与 community.py:121 的 User.tech_tags.contains([tag]) 写法保持一致。
            # 注意：tags 列类型为 JSON().with_variant(JSONB)，ColumnElement.contains
            # 会退化成字符串 LIKE（运行时报 invalid input syntax for type json）；
            # 用 type_coerce 显式按 JSONB 比较，走 @> 包含（2026-08-10 回归修复）。
            conditions.append(
                type_coerce(CommunityPost.tags, JSONB).contains([tag.strip()])
            )
        if series_id:
            conditions.append(CommunityPost.series_id == series_id)
        if author_id:
            conditions.append(CommunityPost.author_id == author_id)
        if following_ids:
            conditions.append(CommunityPost.author_id.in_(following_ids))
        if search and search.strip():
            # 全文检索：search_vector @@ websearch_to_tsquery（GIN 索引加速，AND 语义）
            ts_query = func.websearch_to_tsquery(
                text(f"'{settings.FTS_CONFIG}'"), search.strip()
            )
            conditions.append(CommunityPost.search_vector.op("@@")(ts_query))

        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(CommunityPost).where(*conditions)
                )
            ).scalar_one()
        )
        order = {
            "hot": (
                CommunityPost.is_pinned.desc(),
                CommunityPost.reply_count.desc(),
                CommunityPost.like_count.desc(),
            ),
            "top": (
                CommunityPost.is_pinned.desc(),
                CommunityPost.like_count.desc(),
                CommunityPost.view_count.desc(),
            ),
            "latest": (
                CommunityPost.is_pinned.desc(),
                CommunityPost.last_reply_at.is_(None),
                CommunityPost.last_reply_at.desc(),
                CommunityPost.created_at.desc(),
            ),
        }.get(sort, ())
        stmt = (
            select(CommunityPost)
            .where(*conditions)
            .order_by(*order)
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, post_id: int) -> Optional[CommunityPost]:
        return await self.db.get(CommunityPost, post_id)

    async def get_by_slug(self, slug: str) -> Optional[CommunityPost]:
        stmt = select(CommunityPost).where(CommunityPost.slug == slug)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(CommunityPost.id).where(CommunityPost.slug == slug).limit(1)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none() is not None

    async def create(self, data: dict) -> CommunityPost:
        obj = CommunityPost(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, post: CommunityPost, data: dict) -> None:
        for key, value in data.items():
            setattr(post, key, value)

    async def set_status(self, post_id: int, status: str) -> None:
        post = await self.get_by_id(post_id)
        if post is None:
            return
        post.status = status
        post.updated_at = now_utc()

    async def toggle_pinned(self, post_id: int, pinned: bool) -> None:
        post = await self.get_by_id(post_id)
        if post is None:
            return
        post.is_pinned = pinned

    async def toggle_featured(self, post_id: int, featured: bool) -> None:
        post = await self.get_by_id(post_id)
        if post is None:
            return
        post.is_featured = featured

    async def increment_view(self, post_id: int) -> None:
        post = await self.get_by_id(post_id)
        if post is None:
            return
        post.view_count += 1

    async def adjust_count(
        self, post_id: int, *, reply_delta: int = 0, favorite_delta: int = 0
    ) -> None:
        post = await self.get_by_id(post_id)
        if post is None:
            return
        if reply_delta:
            post.reply_count = max(post.reply_count + reply_delta, 0)
        if favorite_delta:
            post.favorite_count = max(post.favorite_count + favorite_delta, 0)
        if reply_delta or favorite_delta:
            post.updated_at = now_utc()

    async def set_last_reply(self, post_id: int, comment_id: int) -> None:
        post = await self.get_by_id(post_id)
        if post is None:
            return
        post.last_reply_id = comment_id
        post.last_reply_at = now_utc()

    async def adjust_category_count(self, category_id: int, delta: int) -> None:
        if category_id is None:
            return
        category = await self.db.get(CommunityCategory, category_id)
        if category is None:
            return
        category.post_count = max(category.post_count + delta, 0)


class CommunityCommentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_post(
        self, post_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityComment], int]:
        conditions = [
            CommunityComment.post_id == post_id,
            CommunityComment.status == "published",
            CommunityComment.parent_comment_id.is_(None),
        ]
        total = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityComment)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        stmt = (
            select(CommunityComment)
            .where(*conditions)
            .order_by(CommunityComment.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def list_nested(self, parent_comment_id: int) -> list[CommunityComment]:
        stmt = (
            select(CommunityComment)
            .where(
                CommunityComment.parent_comment_id == parent_comment_id,
                CommunityComment.status == "published",
            )
            .order_by(CommunityComment.created_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_for_author(
        self, author_id: int, *, skip: int, limit: int
    ) -> tuple[list[CommunityComment], int]:
        conditions = [
            CommunityComment.author_id == author_id,
            CommunityComment.status == "published",
        ]
        total = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityComment)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        stmt = (
            select(CommunityComment)
            .where(*conditions)
            .order_by(CommunityComment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, comment_id: int) -> Optional[CommunityComment]:
        return await self.db.get(CommunityComment, comment_id)

    async def create(self, data: dict) -> CommunityComment:
        obj = CommunityComment(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, comment: CommunityComment, content: str) -> None:
        comment.content_markdown = content
        comment.updated_at = now_utc()

    async def set_status(self, comment_id: int, status: str) -> None:
        comment = await self.get_by_id(comment_id)
        if comment is None:
            return
        comment.status = status
        comment.updated_at = now_utc()


class CommunityInteractionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_reaction(
        self, user_id: int, target_type: str, target_id: int
    ) -> Optional[CommunityReaction]:
        stmt = select(CommunityReaction).where(
            CommunityReaction.user_id == user_id,
            CommunityReaction.target_type == target_type,
            CommunityReaction.target_id == target_id,
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def add_reaction(
        self, user_id: int, target_type: str, target_id: int
    ) -> None:
        self.db.add(
            CommunityReaction(
                user_id=user_id, target_type=target_type, target_id=target_id
            )
        )
        await self.db.flush()

    async def remove_reaction(self, reaction: CommunityReaction) -> None:
        await self.db.delete(reaction)

    async def get_favorite(
        self, user_id: int, target_type: str, target_id: int
    ) -> Optional[CommunityFavorite]:
        stmt = select(CommunityFavorite).where(
            CommunityFavorite.user_id == user_id,
            CommunityFavorite.target_type == target_type,
            CommunityFavorite.target_id == target_id,
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def get_interaction_target_ids(
        self, user_id: int, target_type: str, target_ids: list[int]
    ) -> dict[str, set[int]]:
        """批量取回某用户对一批目标的点赞/收藏存在集合，消除 N+1。

        返回 {"reaction": set[int], "favorite": set[int]}，值为命中的 target_id 集合。
        target_ids 为空时直接短路返回空集合，避免生成 IN () 空查询。
        """
        if not target_ids:
            return {"reaction": set(), "favorite": set()}
        reaction_ids = set(
            (
                await self.db.execute(
                    select(CommunityReaction.target_id).where(
                        CommunityReaction.user_id == user_id,
                        CommunityReaction.target_type == target_type,
                        CommunityReaction.target_id.in_(target_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        favorite_ids = set(
            (
                await self.db.execute(
                    select(CommunityFavorite.target_id).where(
                        CommunityFavorite.user_id == user_id,
                        CommunityFavorite.target_type == target_type,
                        CommunityFavorite.target_id.in_(target_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {"reaction": reaction_ids, "favorite": favorite_ids}

    async def add_favorite(
        self, user_id: int, target_type: str, target_id: int
    ) -> None:
        self.db.add(
            CommunityFavorite(
                user_id=user_id, target_type=target_type, target_id=target_id
            )
        )
        await self.db.flush()

    async def remove_favorite(self, favorite: CommunityFavorite) -> None:
        await self.db.delete(favorite)

    async def list_favorite_posts(
        self, user_id: int, *, skip: int, limit: int
    ) -> tuple[list[CommunityPost], int]:
        stmt = (
            select(CommunityPost)
            .join(CommunityFavorite, CommunityFavorite.target_id == CommunityPost.id)
            .where(
                CommunityFavorite.user_id == user_id,
                CommunityFavorite.target_type == "post",
                CommunityPost.status == "published",
            )
            .order_by(CommunityFavorite.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        total = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityFavorite)
                    .where(CommunityFavorite.user_id == user_id)
                )
            ).scalar_one()
        )
        return list(rows.scalars().all()), total

    async def has_viewed_recently(
        self, post_id: int, *, user_id: Optional[int], ip_hash: Optional[str]
    ) -> bool:
        since = now_utc() - timedelta(hours=VIEW_DEDUP_WINDOW_HOURS)
        if user_id:
            stmt = select(CommunityPostView.id).where(
                CommunityPostView.post_id == post_id,
                CommunityPostView.user_id == user_id,
                CommunityPostView.viewed_at >= since,
            )
        elif ip_hash:
            stmt = select(CommunityPostView.id).where(
                CommunityPostView.post_id == post_id,
                CommunityPostView.user_id.is_(None),
                CommunityPostView.ip_hash == ip_hash,
                CommunityPostView.viewed_at >= since,
            )
        else:
            return False
        rows = await self.db.execute(stmt.limit(1))
        return rows.scalar_one_or_none() is not None

    async def add_view(
        self, post_id: int, *, user_id: Optional[int], ip_hash: Optional[str]
    ) -> None:
        self.db.add(
            CommunityPostView(post_id=post_id, user_id=user_id, ip_hash=ip_hash)
        )
        await self.db.flush()

    async def create_mentions(self, mentions: list[dict]) -> None:
        for m in mentions:
            self.db.add(CommunityMention(**m))
        await self.db.flush()

    async def list_mentions(
        self, user_id: int, limit: int = 20
    ) -> list[CommunityMention]:
        stmt = (
            select(CommunityMention)
            .where(CommunityMention.mentioned_user_id == user_id)
            .order_by(CommunityMention.created_at.desc())
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())


class CommunityFollowRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, follower_id: int, following_id: int
    ) -> Optional[CommunityFollow]:
        stmt = select(CommunityFollow).where(
            CommunityFollow.follower_id == follower_id,
            CommunityFollow.following_id == following_id,
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def create(self, follower_id: int, following_id: int) -> CommunityFollow:
        obj = CommunityFollow(follower_id=follower_id, following_id=following_id)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete(self, follow: CommunityFollow) -> None:
        await self.db.delete(follow)

    async def list_following_ids(self, user_id: int) -> list[int]:
        stmt = select(CommunityFollow.following_id).where(
            CommunityFollow.follower_id == user_id
        )
        rows = await self.db.execute(stmt)
        return [r[0] for r in rows.all()]

    async def list_following(
        self, user_id: int, *, skip: int, limit: int
    ) -> tuple[list[User], int]:
        stmt = (
            select(User)
            .join(CommunityFollow, CommunityFollow.following_id == User.id)
            .where(CommunityFollow.follower_id == user_id)
            .order_by(CommunityFollow.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        total = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityFollow)
                    .where(CommunityFollow.follower_id == user_id)
                )
            ).scalar_one()
        )
        return list(rows.scalars().all()), total

    async def list_followers(
        self, user_id: int, *, skip: int, limit: int
    ) -> tuple[list[User], int]:
        stmt = (
            select(User)
            .join(CommunityFollow, CommunityFollow.follower_id == User.id)
            .where(CommunityFollow.following_id == user_id)
            .order_by(CommunityFollow.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        total = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityFollow)
                    .where(CommunityFollow.following_id == user_id)
                )
            ).scalar_one()
        )
        return list(rows.scalars().all()), total

    async def bulk_counts(
        self, user_ids: list[int]
    ) -> dict[int, tuple[int, int]]:
        """批量取回一组用户的 (following, followers) 计数，消除逐用户 N+1。

        返回 {user_id: (following_count, follower_count)}；未出现在聚合结果中的
        用户记为 (0, 0)。user_ids 为空时直接短路返回空字典。
        """
        if not user_ids:
            return {}
        following_stmt = (
            select(CommunityFollow.follower_id, func.count())
            .where(CommunityFollow.follower_id.in_(user_ids))
            .group_by(CommunityFollow.follower_id)
        )
        follower_stmt = (
            select(CommunityFollow.following_id, func.count())
            .where(CommunityFollow.following_id.in_(user_ids))
            .group_by(CommunityFollow.following_id)
        )
        following_rows = (await self.db.execute(following_stmt)).all()
        follower_rows = (await self.db.execute(follower_stmt)).all()
        result: dict[int, tuple[int, int]] = {uid: (0, 0) for uid in user_ids}
        for uid, cnt in following_rows:
            result[uid] = (cnt, result[uid][1])
        for uid, cnt in follower_rows:
            prev = result.get(uid, (0, 0))
            result[uid] = (prev[0], cnt)
        return result

    async def bulk_is_following(
        self, follower_id: int, target_ids: list[int]
    ) -> set[int]:
        """批量取回 follower_id 已关注的 target 集合，消除逐用户 N+1。

        返回 {target_id} 集合；target_ids 为空时直接短路返回空集合。
        """
        if not target_ids:
            return set()
        rows = (
            await self.db.execute(
                select(CommunityFollow.following_id).where(
                    CommunityFollow.follower_id == follower_id,
                    CommunityFollow.following_id.in_(target_ids),
                )
            )
        ).scalars().all()
        return set(rows)

    async def counts(self, user_id: int) -> tuple[int, int]:
        following = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityFollow)
                    .where(CommunityFollow.follower_id == user_id)
                )
            ).scalar_one()
        )
        followers = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityFollow)
                    .where(CommunityFollow.following_id == user_id)
                )
            ).scalar_one()
        )
        return following, followers


class CommunityReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(
        self, *, status: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityReport], int]:
        conditions = []
        if status:
            conditions.append(CommunityReport.status == status)
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(CommunityReport).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = (
            select(CommunityReport)
            .where(*conditions)
            .order_by(CommunityReport.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, report_id: int) -> Optional[CommunityReport]:
        return await self.db.get(CommunityReport, report_id)

    async def create(self, data: dict) -> CommunityReport:
        obj = CommunityReport(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def resolve(
        self, report: CommunityReport, handled_by: int, status: str
    ) -> None:
        report.status = status
        report.handled_by = handled_by
        report.handled_at = now_utc()


class CommunitySeriesRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[CommunitySeries]:
        stmt = select(CommunitySeries).order_by(CommunitySeries.created_at.desc())
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_id(self, series_id: int) -> Optional[CommunitySeries]:
        return await self.db.get(CommunitySeries, series_id)

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(CommunitySeries.id).where(CommunitySeries.slug == slug).limit(1)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none() is not None

    async def create(self, data: dict) -> CommunitySeries:
        obj = CommunitySeries(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete(self, series_id: int) -> bool:
        obj = await self.get_by_id(series_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True
