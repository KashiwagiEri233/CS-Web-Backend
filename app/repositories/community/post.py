"""社区帖子仓储。"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.query_helpers import fts_condition
from app.core.query_helpers import jsonb_contains
from app.core.timezone import now_utc
from app.models.community import CommunityCategory, CommunityPost
from app.repositories.base import paginate


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
            conditions.append(jsonb_contains(CommunityPost.tags, [tag.strip()]))
        if series_id:
            conditions.append(CommunityPost.series_id == series_id)
        if author_id:
            conditions.append(CommunityPost.author_id == author_id)
        if following_ids:
            conditions.append(CommunityPost.author_id.in_(following_ids))
        if search and search.strip():
            # 全文检索：search_vector @@ websearch_to_tsquery（GIN 索引加速，AND 语义）
            conditions.append(fts_condition(CommunityPost, search))

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
        stmt = paginate(
            select(CommunityPost).where(*conditions).order_by(*order), skip, limit
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