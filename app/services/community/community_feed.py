"""社区关注服务（ER-15 Phase 4：从 community_service 拆出关注域）。

- 关注关系 CRUD / 关注/粉丝列表 / 计数聚合
- ``_format_follow_users`` 批量聚合（ER-21 优化落地）；``_notify_follow`` 发领域事件
  （``community.user.followed``，订阅者独立 session 落库，见 Phase 1）

API 契约不变（api/v1/community.py 端点 path/method/响应结构保持）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.models.user import User
from app.repositories.community_repo import CommunityFollowRepository
from app.repositories.user_repo import UserRepository


class FeedService:
    """关注流 / 关注关系服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.follow_repo = CommunityFollowRepository(db)
        self.user_repo = UserRepository(db)

    async def toggle_follow(self, follower_id: int, following_id: int) -> dict:
        if follower_id == following_id:
            raise ConflictException(
                message="不能关注自己",
                error_code=ErrorCode.Validation.VALIDATION_FAILED,
            )
        target = await self.user_repo.get_by_id(following_id)
        if target is None or target.deleted_at is not None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=str(following_id),
            )
        existing = await self.follow_repo.get(follower_id, following_id)
        if existing:
            await self.follow_repo.delete(existing)
            following = False
        else:
            await self.follow_repo.create(follower_id, following_id)
            following = True
            await self._notify_follow(follower_id, target)
        await self.db.commit()
        following_count, follower_count = await self.follow_repo.counts(following_id)
        return {
            "following": following,
            "following_count": following_count,
            "follower_count": follower_count,
        }

    async def is_following(self, follower_id: int, following_id: int) -> bool:
        return (await self.follow_repo.get(follower_id, following_id)) is not None

    async def list_following(
        self,
        user_id: int,
        *,
        current_user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> dict:
        users, total = await self.follow_repo.list_following(
            user_id, skip=skip, limit=limit
        )
        return await self._format_follow_users(users, total, current_user_id)

    async def list_followers(
        self,
        user_id: int,
        *,
        current_user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> dict:
        users, total = await self.follow_repo.list_followers(
            user_id, skip=skip, limit=limit
        )
        return await self._format_follow_users(users, total, current_user_id)

    async def get_follow_counts(self, user_id: int) -> dict:
        following, followers = await self.follow_repo.counts(user_id)
        return {"following": following, "followers": followers}

    async def get_following_ids(self, user_id: int) -> list[int]:
        return await self.follow_repo.list_following_ids(user_id)

    # ------------------------------------------------------------------ 内部

    async def _format_follow_users(
        self, users: list[User], total: int, current_user_id: Optional[int]
    ) -> dict:
        items = []
        user_ids = [u.id for u in users]
        counts_map = await self.follow_repo.bulk_counts(user_ids)
        following_set = (
            await self.follow_repo.bulk_is_following(current_user_id, user_ids)
            if current_user_id
            else set()
        )
        for user in users:
            following_count, follower_count = counts_map.get(user.id, (0, 0))
            items.append(
                {
                    "id": user.id,
                    "display_name": user.display_name,
                    "avatar_url": user.avatar_url,
                    "avatar_type": user.avatar_type or "initial",
                    "bio": user.bio,
                    "tech_tags": user.tech_tags or [],
                    "following_count": following_count,
                    "follower_count": follower_count,
                    "is_following": user.id in following_set,
                }
            )
        return {"items": items, "total": total}

    async def _notify_follow(self, follower_id: int, target: User) -> None:
        try:
            # ER-15 Phase 1：通知改发领域事件（订阅者独立 session 查关注者名并落库）
            event_bus.emit(
                "community.user.followed",
                follower_id=follower_id,
                target_user_id=target.id,
            )
        except Exception:  # noqa: BLE001
            pass
