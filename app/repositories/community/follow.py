"""社区关注仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community import CommunityFollow
from app.models.user import User
from app.repositories.base import paginate


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
        stmt = paginate(
            select(User)
            .join(CommunityFollow, CommunityFollow.following_id == User.id)
            .where(CommunityFollow.follower_id == user_id)
            .order_by(CommunityFollow.created_at.desc()),
            skip,
            limit,
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
        stmt = paginate(
            select(User)
            .join(CommunityFollow, CommunityFollow.follower_id == User.id)
            .where(CommunityFollow.following_id == user_id)
            .order_by(CommunityFollow.created_at.desc()),
            skip,
            limit,
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

    async def bulk_counts(self, user_ids: list[int]) -> dict[int, tuple[int, int]]:
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
            (
                await self.db.execute(
                    select(CommunityFollow.following_id).where(
                        CommunityFollow.follower_id == follower_id,
                        CommunityFollow.following_id.in_(target_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
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
