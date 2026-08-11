"""社区 v2 统一服务：posts（topic|post）/ comments / reactions / favorites / follows /
reports / series / mentions。通知触发：like / reply / favorite / follow / mention。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from typing import Any, Optional

from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.timezone import now_utc
from app.models.community import (
    CommunityCategory,
    CommunityComment,
    CommunityPost,
    CommunityReport,
)
from app.models.user import User
from app.repositories.community_repo import (
    CommunityCategoryRepository,
    CommunityCommentRepository,
    CommunityFollowRepository,
    CommunityInteractionRepository,
    CommunityPostRepository,
    CommunityReportRepository,
    CommunitySeriesRepository,
)
from app.repositories.user_repo import UserRepository
from app.services.notification_service import NotificationService
from app.services.view_count import record_view
from app.utils.mask import mask_email

MENTION_PATTERN = r"@([a-zA-Z0-9_-]{3,50})"

COMMUNITY_LIMITS = {
    "TITLE_MAX": 120,
    "CONTENT_MAX": 20000,
    "COMMENT_MAX": 5000,
    "CATEGORY_NAME_MAX": 50,
    "CATEGORY_DESC_MAX": 200,
    "TAGS_MAX": 10,
    "TAG_MAX": 30,
    "SLUG_MAX": 80,
}


def hash_ip_for_view(ip: str) -> str:
    """匿名化访客 IP 用于浏览去重计数。

    密钥来自 COMMUNITY_IP_HASH_SECRET（强制从环境读取，缺失即 fail-fast）。
    绝不使用硬编码常量——否则匿名化对掌握源码者可逆。
    """
    secret = settings.COMMUNITY_IP_HASH_SECRET
    if not secret:
        raise RuntimeError(
            "COMMUNITY_IP_HASH_SECRET 未配置：拒绝处理访客 IP 匿名化"
        )
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()


def scan_mentions(content: str) -> list[str]:
    return list(dict.fromkeys(re.findall(MENTION_PATTERN, content)))


def generate_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[: COMMUNITY_LIMITS["SLUG_MAX"]].strip("-") or "post"


class CommunityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.category_repo = CommunityCategoryRepository(db)
        self.post_repo = CommunityPostRepository(db)
        self.comment_repo = CommunityCommentRepository(db)
        self.interaction_repo = CommunityInteractionRepository(db)
        self.follow_repo = CommunityFollowRepository(db)
        self.report_repo = CommunityReportRepository(db)
        self.series_repo = CommunitySeriesRepository(db)
        self.user_repo = UserRepository(db)

    # ------------------------------------------------------------------ 分类

    async def list_categories(self) -> list:
        return await self.category_repo.list_all()

    async def get_category(self, category_id: int):
        obj = await self.category_repo.get_by_id(category_id)
        if obj is None:
            raise NotFoundException(
                message="分类不存在",
                resource_type="community_category",
                resource_id=str(category_id),
            )
        return obj

    async def create_category(
        self,
        admin_id: int,
        slug: str,
        name: str,
        description=None,
        icon=None,
        sort_order=0,
    ):
        if await self.category_repo.get_by_slug(slug):
            raise ConflictException(
                message="slug 已存在", error_code=ErrorCode.Conflict.SLUG_EXISTS
            )
        obj = await self.category_repo.create(
            {
                "slug": slug,
                "name": name,
                "description": description,
                "icon": icon,
                "sort_order": sort_order,
                "created_by": admin_id,
            }
        )
        await self.db.commit()
        return obj

    async def update_category(
        self,
        admin_id: int,
        category_id: int,
        slug: str,
        name: str,
        description: Optional[str],
        icon: Optional[str],
        sort_order: int,
    ):
        obj = await self.get_category(category_id)
        if slug and slug != obj.slug:
            if await self.category_repo.get_by_slug(slug):
                raise ConflictException(
                    message="slug 已存在", error_code=ErrorCode.Conflict.SLUG_EXISTS
                )
        await self.category_repo.update(
            obj,
            {
                "slug": slug,
                "name": name,
                "description": description,
                "icon": icon,
                "sort_order": sort_order,
            },
        )
        await self.db.commit()
        return obj

    async def delete_category(self, admin_id: int, category_id: int) -> None:
        if not await self.category_repo.delete(category_id):
            raise NotFoundException(
                message="分类不存在",
                resource_type="community_category",
                resource_id=str(category_id),
            )
        await self.db.commit()

    # ----------------------------------------------------- 帖子（topic | post 统一）

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
        following_only: bool = False,
        current_user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[CommunityPost], int]:
        following_ids = None
        if following_only and current_user_id:
            following_ids = await self.follow_repo.list_following_ids(current_user_id)
            if not following_ids:
                return [], 0
        posts, total = await self.post_repo.list_posts(
            kind=kind,
            status=status,
            category_id=category_id,
            category_slug=category_slug,
            tag=tag,
            series_id=series_id,
            author_id=author_id,
            search=search,
            sort=sort,
            include_hidden=include_hidden,
            following_ids=following_ids,
            skip=skip,
            limit=limit,
        )
        await self._enrich_posts(posts, current_user_id)
        return posts, total

    async def get_post(
        self, post_id: int, current_user_id: Optional[int] = None
    ) -> CommunityPost:
        post = await self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundException(
                message="内容不存在",
                resource_type="community_post",
                resource_id=str(post_id),
            )
        await self._enrich_posts([post], current_user_id)
        return post

    async def get_post_by_slug(
        self, slug: str, current_user_id: Optional[int] = None
    ) -> CommunityPost:
        post = await self.post_repo.get_by_slug(slug)
        if post is None:
            raise NotFoundException(
                message="内容不存在", resource_type="community_post", resource_id=slug
            )
        await self._enrich_posts([post], current_user_id)
        return post

    async def create_post(
        self,
        author_id: int,
        kind: str,
        *,
        title: str,
        content_markdown: str,
        category_id: Optional[int] = None,
        status: str = "published",
        slug: Optional[str] = None,
        excerpt: Optional[str] = None,
        cover_image: Optional[str] = None,
        tags: Optional[list] = None,
        series_id: Optional[int] = None,
        series_order: Optional[int] = None,
    ) -> CommunityPost:
        if kind == "post":
            slug = slug or await self._unique_slug(generate_slug(title))
            if status not in ("draft", "published", "archived"):
                status = "draft"
        else:
            if category_id is None:
                raise ConflictException(
                    message="请选择分类",
                    error_code=ErrorCode.Validation.VALIDATION_FAILED,
                )
            await self.get_category(category_id)
        if category_id:
            await self.post_repo.adjust_category_count(category_id, 1)
        post = await self.post_repo.create(
            {
                "kind": kind,
                "category_id": category_id,
                "author_id": author_id,
                "title": title,
                "content_markdown": content_markdown,
                "status": status,
                "slug": slug,
                "excerpt": excerpt,
                "cover_image": cover_image,
                "tags": tags or [],
                "series_id": series_id,
                "series_order": series_order,
                "published_at": now_utc() if status == "published" else None,
            }
        )
        await self.db.commit()
        await self._notify_mentions(content_markdown, "post", post.id, author_id)
        return post

    async def update_post(
        self, user_id: int, post_id: int, data: dict, is_admin: bool
    ) -> CommunityPost:
        post = await self.get_post(post_id)
        if user_id != post.author_id and not is_admin:
            raise AuthorizationException(
                message="无权编辑该内容",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        if post.status == "deleted":
            raise ConflictException(
                message="内容已删除", error_code=ErrorCode.Conflict.STATUS_CONFLICT
            )
        allowed = {
            "title",
            "content_markdown",
            "status",
            "excerpt",
            "cover_image",
            "tags",
            "series_id",
            "series_order",
            "is_pinned",
            "is_featured",
        }
        payload = {k: v for k, v in data.items() if k in allowed and v is not None}
        if (
            "title" in payload
            and payload["title"] != post.title
            and post.kind == "post"
        ):
            payload["slug"] = await self._unique_slug(generate_slug(payload["title"]))
        if (
            "status" in payload
            and payload["status"] == "published"
            and post.status != "published"
        ):
            payload["published_at"] = now_utc()
        await self.post_repo.update(post, payload)
        await self.db.commit()
        if "content_markdown" in payload:
            await self._notify_mentions(
                payload["content_markdown"], "post", post.id, post.author_id
            )
        return post

    async def delete_post(self, user_id: int, post_id: int, is_admin: bool) -> None:
        """软删除（作者或管理员）。"""
        post = await self.get_post(post_id)
        if user_id != post.author_id and not is_admin:
            raise AuthorizationException(
                message="无权删除该内容",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        if post.status == "deleted":
            return
        if post.status in ("published", "hidden") and post.category_id:
            await self.post_repo.adjust_category_count(post.category_id, -1)
        await self.post_repo.set_status(post_id, "deleted")
        await self.db.commit()

    async def hard_delete_post(self, admin_id: int, post_id: int) -> None:
        post = await self.get_post(post_id)
        if post.status in ("published", "hidden") and post.category_id:
            await self.post_repo.adjust_category_count(post.category_id, -1)
        await self.post_repo.set_status(post_id, "deleted")
        await self.db.commit()

    async def user_drafts(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityPost], int]:
        posts, total = await self.post_repo.list_posts(
            kind="post", status="draft", author_id=user_id, skip=skip, limit=limit
        )
        await self._enrich_posts(posts)
        return posts, total

    async def increment_view(
        self, post_id: int, user_id: Optional[int] = None, ip_hash: Optional[str] = None
    ) -> bool:
        post = await self.post_repo.get_by_id(post_id)
        if post is None or post.status != "published":
            return False
        # 写放大治理：去重 + 计数走 Redis，异步批量落库（见 app/services/view_count.py）。
        # 请求路径不再逐次读写 DB / commit；view_count 变更为最终一致。
        return await record_view(post_id, user_id=user_id, ip_hash=ip_hash)

    # ------------------------------------------------------------------ 审核

    async def hide_post(
        self, admin_id: int, post_id: int, reason: Optional[str]
    ) -> None:
        post = await self.get_post(post_id)
        await self.post_repo.update(
            post,
            {
                "status": "hidden",
                "hidden_by": admin_id,
                "hidden_at": now_utc(),
                "hidden_reason": reason,
            },
        )
        await self.db.commit()

    async def restore_post(self, admin_id: int, post_id: int) -> None:
        post = await self.get_post(post_id)
        await self.post_repo.update(
            post,
            {
                "status": "published",
                "hidden_by": None,
                "hidden_at": None,
                "hidden_reason": None,
            },
        )
        await self.db.commit()

    async def set_post_pinned(self, admin_id: int, post_id: int, pinned: bool) -> None:
        await self.get_post(post_id)
        await self.post_repo.toggle_pinned(post_id, pinned)
        await self.db.commit()

    async def set_post_featured(
        self, admin_id: int, post_id: int, featured: bool
    ) -> None:
        await self.get_post(post_id)
        await self.post_repo.toggle_featured(post_id, featured)
        await self.db.commit()

    async def publish_post(self, admin_id: int, post_id: int) -> CommunityPost:
        post = await self.get_post(post_id)
        await self.post_repo.update(
            post, {"status": "published", "published_at": now_utc()}
        )
        await self.db.commit()
        return post

    async def archive_post(self, admin_id: int, post_id: int) -> CommunityPost:
        post = await self.get_post(post_id)
        await self.post_repo.update(post, {"status": "archived"})
        await self.db.commit()
        return post

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
        await self._notify_mentions(content, "comment", comment.id, author_id)
        # 回复通知（被回复者 + 帖主）
        await self._notify_comment_reply(post, comment, author_id, parent_comment_id)
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
                message="评论已删除", error_code=ErrorCode.Conflict.STATUS_CONFLICT
            )
        await self.comment_repo.update(comment, content)
        await self.db.commit()
        await self._notify_mentions(content, "comment", comment.id, comment.author_id)
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

    # ------------------------------------------------------------------ 点赞/收藏

    async def toggle_like(self, user_id: int, target_type: str, target_id: int) -> dict:
        target: Any = None
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

    async def list_user_favorites(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityPost], int]:
        posts, total = await self.interaction_repo.list_favorite_posts(
            user_id, skip=skip, limit=limit
        )
        await self._enrich_posts(posts, user_id)
        return posts, total

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

    # ------------------------------------------------------------------ 关注

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

    # ------------------------------------------------------------------ 举报

    async def submit_report(
        self,
        reporter_id: int,
        target_type: str,
        target_id: int,
        reason: str,
        detail: Optional[str],
    ) -> CommunityReport:
        if target_type == "post":
            report_target: Any = await self.post_repo.get_by_id(target_id)
        else:
            report_target = await self.comment_repo.get_by_id(target_id)
        if report_target is None:
            raise NotFoundException(
                message="目标不存在",
                resource_type=f"community_{target_type}",
                resource_id=str(target_id),
            )
        report = await self.report_repo.create(
            {
                "reporter_id": reporter_id,
                "target_type": target_type,
                "target_id": target_id,
                "reason": reason,
                "detail": detail,
            }
        )
        await self.db.commit()
        return report

    async def list_reports(
        self, *, status: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityReport], int]:
        return await self.report_repo.list(status=status, skip=skip, limit=limit)

    async def resolve_report(
        self, admin_id: int, report_id: int, status: str
    ) -> CommunityReport:
        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise NotFoundException(
                message="举报不存在",
                resource_type="community_report",
                resource_id=str(report_id),
            )
        await self.report_repo.resolve(report, admin_id, status)
        await self.db.commit()
        return report

    # ------------------------------------------------------------------ 系列

    async def list_series(self) -> list:
        return await self.series_repo.list_all()

    async def create_series(self, user_id: int, title: str, description: Optional[str]):
        slug = await self._unique_series_slug(generate_slug(title))
        series = await self.series_repo.create(
            {
                "title": title,
                "description": description,
                "slug": slug,
                "created_by": user_id,
            }
        )
        await self.db.commit()
        return series

    async def delete_series(self, user_id: int, series_id: int, is_admin: bool) -> None:
        series = await self.series_repo.get_by_id(series_id)
        if series is None:
            raise NotFoundException(
                message="系列不存在",
                resource_type="community_series",
                resource_id=str(series_id),
            )
        if user_id != series.created_by and not is_admin:
            raise AuthorizationException(
                message="无权删除该系列",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        await self.series_repo.delete(series_id)
        await self.db.commit()

    # ------------------------------------------------------------------ 内部

    async def _enrich_posts(
        self, posts: list[CommunityPost], current_user_id: Optional[int] = None
    ) -> None:
        if not posts:
            return
        author_ids = {p.author_id for p in posts}
        category_ids = {p.category_id for p in posts if p.category_id}
        users = {
            u.id: u
            for u in (
                await self.db.execute(select(User).where(User.id.in_(author_ids)))
            )
            .scalars()
            .all()
        }
        categories = {}
        if category_ids:
            categories = {
                c.id: c
                for c in (
                    await self.db.execute(
                        select(CommunityCategory).where(
                            CommunityCategory.id.in_(category_ids)
                        )
                    )
                )
                .scalars()
                .all()
            }
        interaction_ids = {"reaction": set(), "favorite": set()}
        if current_user_id:
            interaction_ids = await self.interaction_repo.get_interaction_target_ids(
                current_user_id, "post", [p.id for p in posts]
            )
        for post in posts:
            user = users.get(post.author_id)
            setattr(
                post,
                "author",
                _to_author_summary(user) if user else None,
            )
            cat = categories.get(post.category_id) if post.category_id else None
            setattr(
                post,
                "category",
                {"id": cat.id, "slug": cat.slug, "name": cat.name} if cat else None,
            )
            setattr(
                post,
                "is_liked_by_me",
                post.id in interaction_ids["reaction"],
            )
            setattr(
                post,
                "is_favorited_by_me",
                post.id in interaction_ids["favorite"],
            )

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
            setattr(comment, "author", _to_author_summary(user) if user else None)

    async def _adjust_like_count(self, table, target_id: int, delta: int) -> int:
        result = await self.db.execute(
            sa_update(table)
            .where(table.id == target_id)
            .values(like_count=func.greatest(table.like_count + delta, 0))
            .returning(table.like_count)
        )
        return int(result.scalar() or 0)

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

    async def _unique_slug(self, base: str) -> str:
        slug = base
        suffix = 2
        while await self.post_repo.slug_exists(slug):
            slug = f"{base[: COMMUNITY_LIMITS['SLUG_MAX'] - 3]}-{suffix}"
            suffix += 1
        return slug

    async def _unique_series_slug(self, base: str) -> str:
        slug = base
        suffix = 2
        while await self.series_repo.slug_exists(slug):
            slug = f"{base[: COMMUNITY_LIMITS['SLUG_MAX'] - 3]}-{suffix}"
            suffix += 1
        return slug

    async def _notify_mentions(
        self, content: str, source_type: str, source_id: int, source_author_id: int
    ) -> None:
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
                    type="reply",
                    title="你在社区中被提及",
                    content="某条内容中提到了你，点击查看。",
                    sender_id=source_author_id,
                )
        except Exception:  # noqa: BLE001 - 提及失败不影响发布
            await self.db.rollback()

    async def _notify_comment_reply(
        self,
        post: CommunityPost,
        comment: CommunityComment,
        author_id: int,
        parent_comment_id: Optional[int],
    ) -> None:
        recipients: dict[int, str] = {}
        if parent_comment_id:
            parent = await self.comment_repo.get_by_id(parent_comment_id)
            if parent is not None and parent.author_id != author_id:
                recipients[parent.author_id] = f"你收到了新的回复：「{post.title}」"
        if post.author_id != author_id and post.author_id not in recipients:
            recipients[post.author_id] = f"你的内容「{post.title}」有新评论"
        if not recipients:
            return
        try:
            notification = NotificationService(self.db)
            for uid, content in recipients.items():
                await notification.create(
                    user_id=uid,
                    type="reply",
                    title="新的回复",
                    content=content,
                    sender_id=author_id,
                )
        except Exception:  # noqa: BLE001
            pass

    async def _notify_like(self, target_type: str, target, actor_id: int) -> None:
        recipient_id = target.author_id
        if recipient_id == actor_id:
            return
        try:
            notification = NotificationService(self.db)
            title = "内容被点赞"
            content = (
                f"你的内容「{target.title}」被点赞"
                if target_type == "post"
                else "你的评论被点赞"
            )
            await notification.create(
                user_id=recipient_id,
                type="like",
                title=title,
                content=content,
                sender_id=actor_id,
            )
        except Exception:  # noqa: BLE001
            pass

    async def _notify_favorite(self, post: CommunityPost, actor_id: int) -> None:
        if post.author_id == actor_id:
            return
        try:
            notification = NotificationService(self.db)
            await notification.create(
                user_id=post.author_id,
                type="favorite",
                title="内容被收藏",
                content=f"你的内容「{post.title}」被收藏",
                sender_id=actor_id,
            )
        except Exception:  # noqa: BLE001
            pass

    async def _notify_follow(self, follower_id: int, target: User) -> None:
        try:
            follower = await self.user_repo.get_by_id(follower_id)
            notification = NotificationService(self.db)
            follower_name = (
                (follower.display_name or follower.username) if follower else "有人"
            )
            await notification.create(
                user_id=target.id,
                type="follow",
                title="新的关注",
                content=f"{follower_name} 关注了你",
                sender_id=follower_id,
            )
        except Exception:  # noqa: BLE001
            pass


def _to_author_summary(user) -> dict:
    return {
        "id": user.id,
        "email": mask_email(user.email) or "",
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "avatar_type": user.avatar_type or "initial",
    }
