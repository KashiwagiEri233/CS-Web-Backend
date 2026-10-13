"""社区互动仓储：reactions / favorites / views / mentions。"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import VIEW_DEDUP_WINDOW_HOURS
from app.core.timezone import now_utc
from app.models.community import (
    CommunityFavorite,
    CommunityMention,
    CommunityPost,
    CommunityPostView,
    CommunityReaction,
)
from app.repositories.base import paginate


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
        stmt = paginate(
            select(CommunityPost)
            .join(CommunityFavorite, CommunityFavorite.target_id == CommunityPost.id)
            .where(
                CommunityFavorite.user_id == user_id,
                CommunityFavorite.target_type == "post",
                CommunityPost.status == "published",
            )
            .order_by(CommunityFavorite.created_at.desc()),
            skip,
            limit,
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