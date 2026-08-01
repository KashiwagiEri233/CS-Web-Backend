"""论坛服务：版块 / 主题 / 回复 / 点赞收藏 / 审核 / 提及 / 浏览 / 上传。"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.timezone import now_utc
from app.models.forum import ForumReply, ForumTopic
from app.models.user import User
from app.repositories.community_repo import (
    ForumCategoryRepository,
    ForumInteractionRepository,
    ForumReplyRepository,
    ForumTopicRepository,
)
from app.repositories.user_repo import UserRepository
from app.schemas.community import MENTION_PATTERN, VIEW_DEDUP_WINDOW_HOURS
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.mask import mask_email

_IP_HASH_SECRET = "forum-ip-hash"


def hash_ip_for_view(ip: str) -> str:
    secret = getattr(settings, "FORUM_IP_HASH_SECRET", None) or _IP_HASH_SECRET
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()


def scan_mentions(content: str) -> list[str]:
    """提取 @username 提及（去重保序）。"""
    return list(dict.fromkeys(re.findall(MENTION_PATTERN, content)))


class ForumService:
    def __init__(self, db: AsyncSession, audit: Optional[AuditService] = None):
        self.db = db
        self.category_repo = ForumCategoryRepository(db)
        self.topic_repo = ForumTopicRepository(db)
        self.reply_repo = ForumReplyRepository(db)
        self.interaction_repo = ForumInteractionRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = audit if audit is not None else AuditService()

    # ------------------------------------------------------------------ 版块

    async def list_categories(self) -> list:
        return await self.category_repo.list_all()

    async def get_category(self, category_id: int):
        obj = await self.category_repo.get_by_id(category_id)
        if obj is None:
            raise NotFoundException(
                message="版块不存在",
                resource_type="forum_category",
                resource_id=str(category_id),
            )
        return obj

    async def create_category(self, admin_id: int, data):
        if await self.category_repo.get_by_slug(data.slug):
            raise ConflictException(
                message="slug 已存在", error_code=ErrorCode.Conflict.SLUG_EXISTS
            )
        obj = await self.category_repo.create(
            {
                "slug": data.slug,
                "name": data.name,
                "description": data.description,
                "icon": data.icon,
                "sort_order": data.sort_order,
                "created_by": admin_id,
            }
        )
        await self.db.commit()
        await self._audit(
            "forum.category_create",
            admin_id,
            obj.id,
            {"slug": data.slug, "name": data.name},
        )
        return obj

    async def update_category(self, admin_id: int, category_id: int, data):
        obj = await self.get_category(category_id)
        if data.slug is not None and data.slug != obj.slug:
            if await self.category_repo.get_by_slug(data.slug):
                raise ConflictException(
                    message="slug 已存在", error_code=ErrorCode.Conflict.SLUG_EXISTS
                )
        await self.category_repo.update(
            obj,
            {k: v for k, v in data.model_dump(exclude_unset=True).items()},
        )
        await self.db.commit()
        await self._audit(
            "forum.category_update",
            admin_id,
            obj.id,
            {"fields": list(data.model_dump(exclude_unset=True).keys())},
        )
        return obj

    async def delete_category(self, admin_id: int, category_id: int) -> None:
        if not await self.category_repo.delete(category_id):
            raise NotFoundException(
                message="版块不存在",
                resource_type="forum_category",
                resource_id=str(category_id),
            )
        await self.db.commit()
        await self._audit("forum.category_delete", admin_id, category_id, {})

    # ------------------------------------------------------------------ 主题

    async def list_topics(
        self,
        *,
        category_id: Optional[int] = None,
        search: Optional[str] = None,
        status: Optional[str] = None,
        author_id: Optional[int] = None,
        sort: str = "latest",
        include_hidden: bool = False,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[ForumTopic], int]:
        topics, total = await self.topic_repo.list_topics(
            category_id=category_id,
            search=search,
            status=status,
            include_hidden=include_hidden,
            author_id=author_id,
            sort=sort,
            skip=skip,
            limit=limit,
        )
        await self._load_topic_authors_and_categories(topics)
        return topics, total

    async def get_topic(
        self, topic_id: int, current_user_id: Optional[int] = None
    ) -> ForumTopic:
        topic = await self.topic_repo.get_by_id(topic_id)
        if topic is None:
            raise NotFoundException(
                message="主题不存在",
                resource_type="forum_topic",
                resource_id=str(topic_id),
            )
        await self._load_topic_authors_and_categories([topic])
        if current_user_id:
            setattr(
                topic,
                "is_liked_by_me",
                (
                    await self.interaction_repo.get_like(
                        current_user_id, "topic", topic_id
                    )
                )
                is not None,
            )
            setattr(
                topic,
                "is_favorited_by_me",
                (await self.interaction_repo.get_favorite(current_user_id, topic_id))
                is not None,
            )
        return topic

    async def create_topic(self, author_id: int, data) -> ForumTopic:
        category = await self.category_repo.get_by_id(data.category_id)
        if category is None:
            raise NotFoundException(
                message="版块不存在",
                resource_type="forum_category",
                resource_id=str(data.category_id),
            )
        topic = await self.topic_repo.create(
            {
                "category_id": data.category_id,
                "author_id": author_id,
                "title": data.title,
                "content_markdown": data.content_markdown,
            }
        )
        await self.category_repo.adjust_counts(data.category_id, 1, 1)
        await self.db.commit()
        await self._notify_mentions(data.content_markdown, "topic", topic.id, author_id)
        return topic

    async def update_topic(
        self, user_id: int, is_admin: bool, topic_id: int, data
    ) -> ForumTopic:
        topic = await self.topic_repo.get_by_id(topic_id)
        if topic is None:
            raise NotFoundException(
                message="主题不存在",
                resource_type="forum_topic",
                resource_id=str(topic_id),
            )
        self._assert_ownership(user_id, topic.author_id, is_admin, "主题", "编辑")
        if topic.status == "deleted":
            raise ConflictException(
                message="主题已删除", error_code=ErrorCode.Conflict.STATUS_CONFLICT
            )
        await self.topic_repo.update(
            topic,
            {
                k: v
                for k, v in data.model_dump(exclude_unset=True).items()
                if v is not None
            },
        )
        await self.db.commit()
        await self._notify_mentions(
            topic.content_markdown, "topic", topic.id, topic.author_id
        )
        return topic

    async def delete_topic(self, user_id: int, is_admin: bool, topic_id: int) -> None:
        """作者软删除（status → deleted，终态）。"""
        topic = await self.topic_repo.get_by_id(topic_id)
        if topic is None:
            raise NotFoundException(
                message="主题不存在",
                resource_type="forum_topic",
                resource_id=str(topic_id),
            )
        self._assert_ownership(user_id, topic.author_id, is_admin, "主题", "删除")
        if topic.status == "deleted":
            return
        await self.topic_repo.set_status(topic_id, "deleted")
        if topic.status in ("published", "hidden"):
            await self.category_repo.adjust_counts(topic.category_id, -1, -1)
        await self.db.commit()

    async def record_topic_view(
        self,
        topic_id: int,
        user_id: Optional[int] = None,
        ip_hash: Optional[str] = None,
    ) -> bool:
        topic = await self.topic_repo.get_by_id(topic_id)
        if topic is None or topic.status != "published":
            return False
        since = now_utc() - timedelta(hours=VIEW_DEDUP_WINDOW_HOURS)
        if await self.interaction_repo.has_viewed_recently(
            topic_id, user_id=user_id, ip_hash=ip_hash, since=since
        ):
            return False
        try:
            await self.interaction_repo.add_view(
                topic_id, user_id=user_id, ip_hash=ip_hash
            )
            await self.topic_repo.increment_view(topic_id)
            await self.db.commit()
            return True
        except Exception:
            await self.db.rollback()
            return False  # partial unique index 冲突（并发）视为已记录

    # ------------------------------------------------------------------ 回复

    async def list_replies(
        self, topic_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[ForumReply], int]:
        replies, total = await self.reply_repo.list_for_topic(
            topic_id, skip=skip, limit=limit
        )
        await self._load_reply_authors(replies)
        return replies, total

    async def list_nested_replies(self, parent_reply_id: int) -> list[ForumReply]:
        replies = await self.reply_repo.list_nested(parent_reply_id)
        await self._load_reply_authors(replies)
        return replies

    async def create_reply(self, author_id: int, topic_id: int, data) -> ForumReply:
        topic = await self.topic_repo.get_by_id(topic_id)
        if topic is None or topic.status != "published":
            raise NotFoundException(
                message="主题不存在或已删除",
                resource_type="forum_topic",
                resource_id=str(topic_id),
            )
        reply = await self.reply_repo.create(
            {
                "topic_id": topic_id,
                "author_id": author_id,
                "parent_reply_id": data.parent_reply_id,
                "content_markdown": data.content_markdown,
            }
        )
        # 反范式：主题 reply_count + 主回复 reply_count + last_reply
        await self.db.execute(
            update(ForumTopic)
            .where(ForumTopic.id == topic_id)
            .values(
                reply_count=ForumTopic.reply_count + 1,
                last_reply_id=reply.id,
                last_reply_at=now_utc(),
            )
        )
        if data.parent_reply_id:
            parent = await self.reply_repo.get_by_id(data.parent_reply_id)
            if parent is not None:
                await self.db.execute(
                    update(ForumReply)
                    .where(ForumReply.id == parent.id)
                    .values(reply_count=ForumReply.reply_count + 1)
                )
        await self.category_repo.adjust_counts(topic.category_id, 0, 1)
        await self.db.commit()
        await self._notify_mentions(
            data.content_markdown, "reply", reply.id, author_id, topic_id=topic_id
        )
        return reply

    async def update_reply(
        self, user_id: int, is_admin: bool, reply_id: int, content: str
    ) -> ForumReply:
        reply = await self.reply_repo.get_by_id(reply_id)
        if reply is None:
            raise NotFoundException(
                message="回复不存在",
                resource_type="forum_reply",
                resource_id=str(reply_id),
            )
        self._assert_ownership(user_id, reply.author_id, is_admin, "回复", "编辑")
        if reply.status == "deleted":
            raise ConflictException(
                message="回复已删除", error_code=ErrorCode.Conflict.STATUS_CONFLICT
            )
        await self.reply_repo.update(reply, content)
        await self.db.commit()
        await self._notify_mentions(
            content, "reply", reply.id, reply.author_id, topic_id=reply.topic_id
        )
        return reply

    async def delete_reply(self, user_id: int, is_admin: bool, reply_id: int) -> None:
        reply = await self.reply_repo.get_by_id(reply_id)
        if reply is None:
            raise NotFoundException(
                message="回复不存在",
                resource_type="forum_reply",
                resource_id=str(reply_id),
            )
        self._assert_ownership(user_id, reply.author_id, is_admin, "回复", "删除")
        if reply.status == "deleted":
            return
        await self.reply_repo.set_status(reply_id, "deleted")
        await self.db.commit()

    # ------------------------------------------------------------------ 点赞/收藏

    async def toggle_like(self, user_id: int, target_type: str, target_id: int) -> dict:
        if target_type == "topic":
            topic = await self.topic_repo.get_by_id(target_id)
            if topic is None or topic.status != "published":
                raise NotFoundException(
                    message="目标不存在或已删除",
                    resource_type="forum_topic",
                    resource_id=str(target_id),
                )
        else:
            reply = await self.reply_repo.get_by_id(target_id)
            if reply is None or reply.status != "published":
                raise NotFoundException(
                    message="目标不存在或已删除",
                    resource_type="forum_reply",
                    resource_id=str(target_id),
                )
        existing = await self.interaction_repo.get_like(user_id, target_type, target_id)
        table = ForumTopic if target_type == "topic" else ForumReply
        if existing:
            await self.interaction_repo.remove_like(existing)
            count = await self.interaction_repo.adjust_like_count(table, target_id, -1)
            liked = False
        else:
            await self.interaction_repo.add_like(user_id, target_type, target_id)
            count = await self.interaction_repo.adjust_like_count(table, target_id, 1)
            liked = True
        await self.db.commit()
        return {"liked": liked, "like_count": count}

    async def toggle_favorite(self, user_id: int, topic_id: int) -> dict:
        topic = await self.topic_repo.get_by_id(topic_id)
        if topic is None or topic.status != "published":
            raise NotFoundException(
                message="主题不存在或已删除",
                resource_type="forum_topic",
                resource_id=str(topic_id),
            )
        existing = await self.interaction_repo.get_favorite(user_id, topic_id)
        if existing:
            await self.interaction_repo.remove_favorite(existing)
            count = await self.interaction_repo.adjust_favorite_count(topic_id, -1)
            favorited = False
        else:
            await self.interaction_repo.add_favorite(user_id, topic_id)
            count = await self.interaction_repo.adjust_favorite_count(topic_id, 1)
            favorited = True
        await self.db.commit()
        return {"favorited": favorited, "favorite_count": count}

    async def list_user_favorites(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[ForumTopic], int]:
        topics, total = await self.topic_repo.list_favorites(user_id, skip, limit)
        await self._load_topic_authors_and_categories(topics)
        return topics, total

    # ------------------------------------------------------------------ 审核（管理）

    async def hide_topic(
        self, admin_id: int, topic_id: int, reason: Optional[str]
    ) -> None:
        topic = await self._require_topic(topic_id)
        await self.topic_repo.update(
            topic,
            {
                "status": "hidden",
                "hidden_by": admin_id,
                "hidden_at": now_utc(),
                "hidden_reason": reason,
            },
        )
        await self.db.commit()

    async def restore_topic(self, admin_id: int, topic_id: int) -> None:
        topic = await self._require_topic(topic_id)
        await self.topic_repo.update(
            topic,
            {
                "status": "published",
                "hidden_by": None,
                "hidden_at": None,
                "hidden_reason": None,
            },
        )
        await self.db.commit()

    async def set_topic_pinned(
        self, admin_id: int, topic_id: int, pinned: bool
    ) -> None:
        await self._require_topic(topic_id)
        await self.topic_repo.toggle_pinned(topic_id, pinned)
        await self.db.commit()

    async def set_topic_featured(
        self, admin_id: int, topic_id: int, featured: bool
    ) -> None:
        await self._require_topic(topic_id)
        await self.topic_repo.toggle_featured(topic_id, featured)
        await self.db.commit()

    async def hard_delete_topic(self, admin_id: int, topic_id: int) -> None:
        topic = await self._require_topic(topic_id)
        if topic.status in ("published", "hidden"):
            await self.category_repo.adjust_counts(topic.category_id, -1, -1)
        await self.topic_repo.hard_delete(topic_id)
        await self.db.commit()

    async def hide_reply(
        self, admin_id: int, reply_id: int, reason: Optional[str]
    ) -> None:
        reply = await self.reply_repo.get_by_id(reply_id)
        if reply is None:
            raise NotFoundException(
                message="回复不存在",
                resource_type="forum_reply",
                resource_id=str(reply_id),
            )
        reply.status = "hidden"
        reply.hidden_by = admin_id
        reply.hidden_at = now_utc()
        reply.hidden_reason = reason
        await self.db.commit()

    async def restore_reply(self, admin_id: int, reply_id: int) -> None:
        reply = await self.reply_repo.get_by_id(reply_id)
        if reply is None:
            raise NotFoundException(
                message="回复不存在",
                resource_type="forum_reply",
                resource_id=str(reply_id),
            )
        reply.status = "published"
        reply.hidden_by = None
        reply.hidden_at = None
        reply.hidden_reason = None
        await self.db.commit()

    async def hard_delete_reply(self, admin_id: int, reply_id: int) -> None:
        reply = await self.reply_repo.get_by_id(reply_id)
        if reply is None:
            raise NotFoundException(
                message="回复不存在",
                resource_type="forum_reply",
                resource_id=str(reply_id),
            )
        await self.reply_repo.hard_delete(reply_id)
        await self.db.commit()

    # ------------------------------------------------------------------ 用户数据

    async def list_user_topics(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[ForumTopic], int]:
        topics, total = await self.topic_repo.list_topics(
            author_id=user_id, skip=skip, limit=limit
        )
        await self._load_topic_authors_and_categories(topics)
        return topics, total

    async def list_user_replies(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[ForumReply], int]:
        return await self.reply_repo.list_for_author(user_id, skip=skip, limit=limit)

    async def list_mentions(self, user_id: int, limit: int = 20) -> list:
        return await self.interaction_repo.list_mentions(user_id, limit)

    # ------------------------------------------------------------------ 内部

    async def _require_topic(self, topic_id: int) -> ForumTopic:
        topic = await self.topic_repo.get_by_id(topic_id)
        if topic is None:
            raise NotFoundException(
                message="主题不存在",
                resource_type="forum_topic",
                resource_id=str(topic_id),
            )
        return topic

    def _assert_ownership(
        self, user_id: int, author_id: int, is_admin: bool, resource: str, action: str
    ) -> None:
        if user_id != author_id and not is_admin:
            raise AuthorizationException(
                message=f"无权{action}该{resource}",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )

    async def _load_topic_authors_and_categories(
        self, topics: list[ForumTopic]
    ) -> None:
        from app.models.forum import ForumCategory

        if not topics:
            return
        author_ids = {t.author_id for t in topics}
        category_ids = {t.category_id for t in topics}
        users = {
            u.id: u
            for u in (
                await self.db.execute(select(User).where(User.id.in_(author_ids)))
            )
            .scalars()
            .all()
        }
        categories = {
            c.id: c
            for c in (
                await self.db.execute(
                    select(ForumCategory).where(ForumCategory.id.in_(category_ids))
                )
            )
            .scalars()
            .all()
        }
        for topic in topics:
            user = users.get(topic.author_id)
            setattr(topic, "author", _to_author_summary(user) if user else None)
            cat = categories.get(topic.category_id)
            setattr(
                topic,
                "category",
                {"id": cat.id, "slug": cat.slug, "name": cat.name} if cat else None,
            )

    async def _load_reply_authors(self, replies: list[ForumReply]) -> None:
        if not replies:
            return
        author_ids = {r.author_id for r in replies}
        users = {
            u.id: u
            for u in (
                await self.db.execute(select(User).where(User.id.in_(author_ids)))
            )
            .scalars()
            .all()
        }
        for reply in replies:
            user = users.get(reply.author_id)
            setattr(reply, "author", _to_author_summary(user) if user else None)

    async def _notify_mentions(
        self,
        content: str,
        source_type: str,
        source_id: int,
        source_author_id: int,
        topic_id: Optional[int] = None,
    ) -> None:
        """扫描 @提及 → forum_mentions + 站内通知（失败不阻断业务）。"""
        usernames = scan_mentions(content)
        if not usernames:
            return
        try:
            rows = (
                (
                    await self.db.execute(
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
            await self.interaction_repo.create_mentions(
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
            await self.db.commit()
            notification = NotificationService(self.db)
            for u in mentioned:
                await notification.create(
                    user_id=u.id,
                    type="system",
                    title="你在论坛回复中被提及",
                    content="某条回复中提到了你，点击查看。",
                    sender_id=source_author_id,
                )
        except Exception:  # noqa: BLE001 - 提及失败不影响发帖
            await self.db.rollback()

    async def _audit(
        self, action: str, actor_id: int, resource_id: int, detail: dict
    ) -> None:
        user = await self.user_repo.get_by_id(actor_id)
        await self.audit.record(
            action=action,
            resource_type="forum",
            resource_id=str(resource_id),
            actor_id=actor_id,
            actor_username=user.username if user else None,
            detail=detail,
        )


def _to_author_summary(user) -> dict:
    return {
        "id": user.id,
        "email": mask_email(user.email) or "",
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "avatar_type": user.avatar_type or "initial",
    }
