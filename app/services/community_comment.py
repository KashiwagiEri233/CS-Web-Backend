"""社区评论服务（ER-15 Phase 3：从 community_service 拆出 Comment 域）。

- 评论楼中楼 / CRUD / 软删 / 审核隐藏恢复
- ``create_comment`` / ``delete_comment`` 同步维护 post 反范式计数（reply_count / last_reply_id）
- 提及与回复通知经 ``community_notifications`` 共享模块（领域事件）

API 契约不变（api/v1/community.py 端点 path/method/响应结构保持）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.timezone import now_utc
from app.models.community import CommunityComment
from app.models.user import User
from app.repositories.community_repo import (
    CommunityCommentRepository,
    CommunityPostRepository,
)
from app.services.community_notifications import notify_comment_reply, notify_mentions
from app.services.community_utils import to_author_summary


class CommentService:
    """评论（comments）服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.comment_repo = CommunityCommentRepository(db)
        self.post_repo = CommunityPostRepository(db)

    # ------------------------------------------------------------------ 评论

    async def list_comments(
        self, post_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityComment], int]:
        comments, total = await self.comment_repo.list_for_post(
            post_id, skip=skip, limit=limit
        )
        await self._load_author_summaries(comments)
        return comments, total

    async def list_nested_comments(
        self, parent_comment_id: int
    ) -> list[CommunityComment]:
        comments = await self.comment_repo.list_nested(parent_comment_id)
        await self._load_author_summaries(comments)
        return comments

    async def list_by_author(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityComment], int]:
        comments, total = await self.comment_repo.list_for_author(
            user_id, skip=skip, limit=limit
        )
        await self._load_author_summaries(comments)
        return comments, total

    async def create_comment(
        self,
        author_id: int,
        post_id: int,
        content: str,
        parent_comment_id: Optional[int] = None,
    ) -> CommunityComment:
        post = await self.post_repo.get_by_id(post_id)
        if post is None or post.status != "published":
            raise NotFoundException(
                message="内容不存在或已删除",
                resource_type="community_post",
                resource_id=str(post_id),
            )
        comment = await self.comment_repo.create(
            {
                "post_id": post_id,
                "author_id": author_id,
                "parent_comment_id": parent_comment_id,
                "content_markdown": content,
            }
        )
        await self.post_repo.adjust_count(post_id, reply_delta=1)
        await self.post_repo.set_last_reply(post_id, comment.id)
        if parent_comment_id:
            parent = await self.comment_repo.get_by_id(parent_comment_id)
            if parent is not None:
                parent.reply_count += 1
        await self.db.commit()
        await notify_mentions(self.db, content, "comment", comment.id, author_id)
        # 回复通知（被回复者 + 帖主）
        await notify_comment_reply(self.db, post, comment, author_id, parent_comment_id)
        return comment

    async def update_comment(
        self, user_id: int, is_admin: bool, comment_id: int, content: str
    ) -> CommunityComment:
        comment = await self.comment_repo.get_by_id(comment_id)
        if comment is None:
            raise NotFoundException(
                message="评论不存在",
                resource_type="community_comment",
                resource_id=str(comment_id),
            )
        if user_id != comment.author_id and not is_admin:
            raise AuthorizationException(
                message="无权编辑该评论",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        if comment.status == "deleted":
            raise ConflictException(
                message="评论已删除", error_code=ErrorCode.Community.STATUS_CONFLICT
            )
        await self.comment_repo.update(comment, content)
        await self.db.commit()
        await notify_mentions(
            self.db, content, "comment", comment.id, comment.author_id
        )
        return comment

    async def delete_comment(
        self, user_id: int, is_admin: bool, comment_id: int
    ) -> None:
        comment = await self.comment_repo.get_by_id(comment_id)
        if comment is None:
            raise NotFoundException(
                message="评论不存在",
                resource_type="community_comment",
                resource_id=str(comment_id),
            )
        if user_id != comment.author_id and not is_admin:
            raise AuthorizationException(
                message="无权删除该评论",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        if comment.status == "deleted":
            return
        await self.comment_repo.set_status(comment_id, "deleted")
        await self.post_repo.adjust_count(comment.post_id, reply_delta=-1)
        await self.db.commit()

    async def hide_comment(
        self, admin_id: int, comment_id: int, reason: Optional[str]
    ) -> None:
        comment = await self.comment_repo.get_by_id(comment_id)
        if comment is None:
            raise NotFoundException(
                message="评论不存在",
                resource_type="community_comment",
                resource_id=str(comment_id),
            )
        comment.status = "hidden"
        comment.hidden_by = admin_id
        comment.hidden_at = now_utc()
        comment.hidden_reason = reason
        await self.db.commit()

    async def restore_comment(self, admin_id: int, comment_id: int) -> None:
        comment = await self.comment_repo.get_by_id(comment_id)
        if comment is None:
            raise NotFoundException(
                message="评论不存在",
                resource_type="community_comment",
                resource_id=str(comment_id),
            )
        comment.status = "published"
        comment.hidden_by = None
        comment.hidden_at = None
        comment.hidden_reason = None
        await self.db.commit()

    async def hard_delete_comment(self, admin_id: int, comment_id: int) -> None:
        comment = await self.comment_repo.get_by_id(comment_id)
        if comment is None:
            raise NotFoundException(
                message="评论不存在",
                resource_type="community_comment",
                resource_id=str(comment_id),
            )
        comment.status = "deleted"
        await self.db.commit()

    # ------------------------------------------------------------------ 内部

    async def _load_author_summaries(self, comments: list[CommunityComment]) -> None:
        if not comments:
            return
        author_ids = {c.author_id for c in comments}
        users = {
            u.id: u
            for u in (
                await self.db.execute(select(User).where(User.id.in_(author_ids)))
            )
            .scalars()
            .all()
        }
        for comment in comments:
            user = users.get(comment.author_id)
            setattr(comment, "author", to_author_summary(user) if user else None)
