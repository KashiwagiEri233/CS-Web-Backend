"""社区共享通知逻辑（ER-15 Phase 3：从 community_service 拆出）。

- ``notify_mentions``：扫描 @提及 → 落库 mentions → 发 ``community.mention`` 领域事件
- ``notify_comment_reply``：评论回复（被回复者 + 帖主）→ 发 ``community.comment.reply`` 领域事件

Post/Comment 服务共用；模块级 async 函数，接收 db 并自行构建所需 repo，
避免子服务互相持有对方实例（子服务之间单向依赖，见 BackDoc-Refactor-CommunityService §3）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.models.community import CommunityComment, CommunityPost
from app.models.user import User
from app.repositories.community_repo import (
    CommunityCommentRepository,
    CommunityInteractionRepository,
)
from app.services.community_utils import scan_mentions


async def notify_mentions(
    db: AsyncSession,
    content: str,
    source_type: str,
    source_id: int,
    source_author_id: int,
) -> None:
    """提及落库 + 领域事件（失败不影响发布）。"""
    usernames = scan_mentions(content)
    if not usernames:
        return
    try:
        rows = (
            (
                await db.execute(
                    select(User).where(
                        User.username.in_(usernames), User.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        mentioned = [u for u in rows if u.id != source_author_id]
        if not mentioned:
            return
        await CommunityInteractionRepository(db).create_mentions(
            [
                {
                    "mentioned_user_id": u.id,
                    "source_type": source_type,
                    "source_id": source_id,
                    "source_author_id": source_author_id,
                }
                for u in mentioned
            ]
        )
        await db.commit()
        # ER-15 Phase 1：通知改发领域事件（notification_events 订阅者独立 session 落库）
        event_bus.emit(
            "community.mention",
            source_type=source_type,
            source_id=source_id,
            source_author_id=source_author_id,
            mentioned_user_ids=[u.id for u in mentioned],
        )
    except Exception:  # noqa: BLE001 - 提及失败不影响发布
        await db.rollback()


async def notify_comment_reply(
    db: AsyncSession,
    post: CommunityPost,
    comment: CommunityComment,
    author_id: int,
    parent_comment_id: Optional[int],
) -> None:
    """评论回复事件：被回复者 + 帖主（排除操作者本人）。"""
    recipients: dict[int, str] = {}
    if parent_comment_id:
        parent = await CommunityCommentRepository(db).get_by_id(parent_comment_id)
        if parent is not None and parent.author_id != author_id:
            recipients[parent.author_id] = f"你收到了新的回复：「{post.title}」"
    if post.author_id != author_id and post.author_id not in recipients:
        recipients[post.author_id] = f"你的内容「{post.title}」有新评论"
    if not recipients:
        return
    try:
        # ER-15 Phase 1：通知改发领域事件（订阅者独立 session 落库）
        event_bus.emit(
            "community.comment.reply",
            post_title=post.title,
            actor_id=author_id,
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001
        pass
