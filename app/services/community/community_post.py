"""社区帖子服务（ER-15 Phase 3：从 community_service 拆出 Post 域）。

- 帖子（topic | post 统一）CRUD / 草稿 / 软删 / 审核隐藏恢复 / 置顶加精 / 发布归档 / 浏览量
- ``list_user_favorites``（收藏列表依赖 ``_enrich_posts``，随本服务）
- 提及通知经 ``community_notifications`` 共享模块（mentions 落库 + 领域事件）

API 契约不变（api/v1/community.py 端点 path/method/响应结构保持）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import COMMUNITY_LIMITS
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.timezone import now_utc
from app.models.community import CommunityCategory, CommunityPost
from app.repositories.community_repo import (
    CommunityCategoryRepository,
    CommunityFollowRepository,
    CommunityInteractionRepository,
    CommunityPostRepository,
)
from app.services.community.community_notifications import notify_mentions
from app.services.community.community_utils import (
    load_users_by_ids,
    generate_slug,
    to_author_summary,
)
from app.services.view_count import record_view


class PostService:
    """帖子（topic | post 统一）服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.post_repo = CommunityPostRepository(db)
        self.category_repo = CommunityCategoryRepository(db)
        self.interaction_repo = CommunityInteractionRepository(db)
        self.follow_repo = CommunityFollowRepository(db)

    # ------------------------------------------------------------------ 分类校验

    async def _get_category(self, category_id: int):
        obj = await self.category_repo.get_by_id(category_id)
        if obj is None:
            raise NotFoundException(
                message="分类不存在",
                resource_type="community_category",
                resource_id=str(category_id),
            )
        return obj

    # ------------------------------------------------------------------ 帖子

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
            await self._get_category(category_id)
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
        await notify_mentions(self.db, content_markdown, "post", post.id, author_id)
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
                message="内容已删除", error_code=ErrorCode.Community.STATUS_CONFLICT
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
            await notify_mentions(
                self.db, payload["content_markdown"], "post", post.id, post.author_id
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

    # ------------------------------------------------------------------ 收藏列表

    async def list_user_favorites(
        self, user_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityPost], int]:
        posts, total = await self.interaction_repo.list_favorite_posts(
            user_id, skip=skip, limit=limit
        )
        await self._enrich_posts(posts, user_id)
        return posts, total

    # ------------------------------------------------------------------ 内部

    async def _enrich_posts(
        self, posts: list[CommunityPost], current_user_id: Optional[int] = None
    ) -> None:
        if not posts:
            return
        category_ids = {p.category_id for p in posts if p.category_id}
        users = await load_users_by_ids(self.db, (p.author_id for p in posts))
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
                to_author_summary(user) if user else None,
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

    async def _unique_slug(self, base: str) -> str:
        slug = base
        suffix = 2
        while await self.post_repo.slug_exists(slug):
            slug = f"{base[: COMMUNITY_LIMITS['SLUG_MAX'] - 3]}-{suffix}"
            suffix += 1
        return slug
