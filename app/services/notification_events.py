"""通知事件订阅：业务事件 → 站内通知（与前端 notification-events.ts 对齐）。

当前订阅：
- user.registered → 欢迎通知
- event.created → 全站广播新活动
- event.registered → 报名成功通知
- event.cancelled → 取消报名通知

订阅者自带独立会话（get_session），业务事务提交后再 emit 即可安全使用。
多实例部署需跨实例广播时（ADR-014），把订阅者内实现迁移到 arq 队列任务。
"""

from __future__ import annotations

from app.core.events import event_bus
from app.core.loguru_logger import get_logger
from app.database import get_session
from app.services.notification_service import NotificationService

logger = get_logger("notification.events")


async def _on_user_registered(user_id: int) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        await service.create(
            user_id=user_id,
            type="system",
            title="欢迎加入",
            content="欢迎加入我们的社区！在这里你可以参与各类活动，结识志同道合的伙伴。",
        )


async def _on_event_created(
    event_id: int, title: str, description=None, admin_id=None
) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        content = (
            f"{description}\n\n点击通知或前往「活动」页面查看详情。"
            if description
            else "点击通知或前往「活动」页面查看详情。"
        )
        await service.broadcast(
            title=f"新活动发布：{title}",
            content=content,
            sender_id=admin_id,
        )


async def _on_event_registered(user_id: int, event_id: int, event_title: str) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        await service.create(
            user_id=user_id,
            type="activity",
            title="活动报名成功",
            content=f"你已成功报名「{event_title}」，我们期待你的参与！",
        )


async def _on_event_cancelled(user_id: int, event_id: int, event_title: str) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        await service.create(
            user_id=user_id,
            type="activity",
            title="活动取消报名",
            content=f"你已取消「{event_title}」的报名。如有疑问请联系管理员。",
        )


# ---- 社区（ER-15 Phase 1：community_service 通知事件化后订阅）----


async def _on_community_mention(
    source_type: str,
    source_id: int,
    source_author_id: int,
    mentioned_user_ids: list[int],
) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        for uid in mentioned_user_ids:
            await service.create(
                user_id=uid,
                type="reply",
                title="你在社区中被提及",
                content="某条内容中提到了你，点击查看。",
                sender_id=source_author_id,
            )


async def _on_community_comment_reply(
    post_title: str, actor_id: int, recipients: dict[int, str]
) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        for uid, content in recipients.items():
            await service.create(
                user_id=uid,
                type="reply",
                title="新的回复",
                content=content,
                sender_id=actor_id,
            )


async def _on_community_post_liked(
    target_type: str, target_title: str, actor_id: int, recipient_id: int
) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        await service.create(
            user_id=recipient_id,
            type="like",
            title="内容被点赞",
            content=(
                f"你的内容「{target_title}」被点赞"
                if target_type == "post"
                else "你的评论被点赞"
            ),
            sender_id=actor_id,
        )


async def _on_community_post_favorited(
    post_title: str, actor_id: int, recipient_id: int
) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        await service.create(
            user_id=recipient_id,
            type="favorite",
            title="内容被收藏",
            content=f"你的内容「{post_title}」被收藏",
            sender_id=actor_id,
        )


async def _on_community_user_followed(
    follower_id: int, target_user_id: int
) -> None:
    async with get_session() as db:
        from app.models.user import User

        follower = await db.get(User, follower_id)
        follower_name = (
            (follower.display_name or follower.username) if follower else "有人"
        )
        service = NotificationService(db)
        await service.create(
            user_id=target_user_id,
            type="follow",
            title="新的关注",
            content=f"{follower_name} 关注了你",
            sender_id=follower_id,
        )


def register_notification_events() -> None:
    """注册全部通知订阅者（幂等，可多次调用）。"""
    event_bus.subscribe("user.registered", _on_user_registered)
    event_bus.subscribe("event.created", _on_event_created)
    event_bus.subscribe("event.registered", _on_event_registered)
    event_bus.subscribe("event.cancelled", _on_event_cancelled)
    event_bus.subscribe("community.mention", _on_community_mention)
    event_bus.subscribe("community.comment.reply", _on_community_comment_reply)
    event_bus.subscribe("community.post.liked", _on_community_post_liked)
    event_bus.subscribe("community.post.favorited", _on_community_post_favorited)
    event_bus.subscribe("community.user.followed", _on_community_user_followed)
    logger.debug("通知事件订阅已注册")
