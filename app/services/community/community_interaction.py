"""社区互动服务（ER-15 Phase 2：从 community_service 拆出点赞/收藏）。

- ReactionService：toggle_like / get_reaction_status（复用 CommunityInteractionRepository）
- FavoriteService：toggle_favorite

反范式计数（like_count / favorite_count）与通知（经事件总线，见 Phase 1）随方法迁移；
API 契约不变（api/v1/community.py 端点 path/method/响应结构保持）。
"""

from typing import Any, Optional

from sqlalchemy import func, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.exceptions import NotFoundException
from app.models.community import CommunityComment, CommunityPost
from app.repositories.community_repo import (
    CommunityCommentRepository,
    CommunityInteractionRepository,
    CommunityPostRepository,
)


class ReactionService:
    """帖子/评论点赞（reactions）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.interaction_repo = CommunityInteractionRepository(db)
        self.post_repo = CommunityPostRepository(db)
        self.comment_repo = CommunityCommentRepository(db)

    async def toggle_like(self, user_id: int, target_type: str, target_id: int) -> dict:
        table = CommunityPost if target_type == "post" else CommunityComment
        if target_type == "post":
            target = await self.post_repo.get_by_id(target_id)
        else:
            target = await self.comment_repo.get_by_id(target_id)
        if target is None or target.status != "published":
            raise NotFoundException(
                message="目标不存在或已删除",
                resource_type=f"community_{target_type}",
                resource_id=str(target_id),
            )
        existing = await self.interaction_repo.get_reaction(
            user_id, target_type, target_id
        )
        if existing:
            await self.interaction_repo.remove_reaction(existing)
            count = await self._adjust_like_count(table, target_id, -1)
            liked = False
        else:
            await self.interaction_repo.add_reaction(user_id, target_type, target_id)
            count = await self._adjust_like_count(table, target_id, 1)
            liked = True
            await self._notify_like(target_type, target, user_id)
        await self.db.commit()
        return {"liked": liked, "like_count": count}

    async def get_reaction_status(
        self, user_id: int, target_type: str, target_id: int
    ) -> dict:
        liked = (
            await self.interaction_repo.get_reaction(user_id, target_type, target_id)
        ) is not None
        favorited = (
            (await self.interaction_repo.get_favorite(user_id, "post", target_id))
            is not None
            if target_type == "post"
            else False
        )
        return {"liked": liked, "favorited": favorited}

    # ----------------------- 内部 -----------------------

    async def _adjust_like_count(self, table, target_id: int, delta: int) -> int:
        result = await self.db.execute(
            sa_update(table)
            .where(table.id == target_id)
            .values(like_count=func.greatest(table.like_count + delta, 0))
            .returning(table.like_count)
        )
        return int(result.scalar() or 0)

    async def _notify_like(self, target_type: str, target, actor_id: int) -> None:
        recipient_id = target.author_id
        if recipient_id == actor_id:
            return
        try:
            event_bus.emit(
                "community.post.liked",
                target_type=target_type,
                target_title=target.title,
                actor_id=actor_id,
                recipient_id=recipient_id,
            )
        except Exception:  # noqa: BLE001
            pass


class FavoriteService:
    """帖子收藏（favorites）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.interaction_repo = CommunityInteractionRepository(db)
        self.post_repo = CommunityPostRepository(db)

    async def toggle_favorite(self, user_id: int, post_id: int) -> dict:
        post = await self.post_repo.get_by_id(post_id)
        if post is None or post.status != "published":
            raise NotFoundException(
                message="内容不存在或已删除",
                resource_type="community_post",
                resource_id=str(post_id),
            )
        existing = await self.interaction_repo.get_favorite(user_id, "post", post_id)
        if existing:
            await self.interaction_repo.remove_favorite(existing)
            count = await self._adjust_count_value(
                CommunityPost, post_id, "favorite_count", -1
            )
            favorited = False
        else:
            await self.interaction_repo.add_favorite(user_id, "post", post_id)
            count = await self._adjust_count_value(
                CommunityPost, post_id, "favorite_count", 1
            )
            favorited = True
            await self._notify_favorite(post, user_id)
        await self.db.commit()
        return {"favorited": favorited, "favorite_count": count}

    # ----------------------- 内部 -----------------------

    async def _adjust_count_value(
        self, table, target_id: int, column: str, delta: int
    ) -> int:
        col = getattr(table, column)
        result = await self.db.execute(
            sa_update(table)
            .where(table.id == target_id)
            .values(**{column: func.greatest(col + delta, 0)})
            .returning(col)
        )
        return int(result.scalar() or 0)

    async def _notify_favorite(self, post: CommunityPost, actor_id: int) -> None:
        if post.author_id == actor_id:
            return
        try:
            event_bus.emit(
                "community.post.favorited",
                post_title=post.title,
                actor_id=actor_id,
                recipient_id=post.author_id,
            )
        except Exception:  # noqa: BLE001
            pass
