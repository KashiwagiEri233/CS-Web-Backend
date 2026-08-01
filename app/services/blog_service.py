"""博客服务：文章 CRUD / 系列 / 点赞浏览 / slug 生成 / TOC。"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    ErrorCode,
    NotFoundException,
)
from app.core.timezone import now_utc
from app.models.blog import BlogPost
from app.models.user import User
from app.repositories.community_repo import BlogRepository
from app.repositories.user_repo import UserRepository
from app.schemas.community import BLOG_LIMITS


def generate_slug(title: str) -> str:
    """标题 → slug（小写、非字母数字转连字符、压缩、截断）。"""
    normalized = unicodedata.normalize("NFKD", title)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[: BLOG_LIMITS["SLUG_MAX"]].strip("-") or "post"


def extract_table_of_contents(markdown: str) -> list[dict]:
    """从 Markdown 提取标题目录（## / ### 级）。"""
    toc: list[dict] = []
    for line in markdown.splitlines():
        m = re.match(r"^(#{2,3})\s+(.+)$", line.strip())
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2).strip()
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff-]+", "-", text).strip("-").lower()
        toc.append({"level": level, "text": text, "slug": slug or "section"})
    return toc


class BlogService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BlogRepository(db)
        self.user_repo = UserRepository(db)

    # ------------------------------------------------------------------ 文章

    async def list_posts(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        author_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[BlogPost], int]:
        posts, total = await self.repo.list_posts(
            status=status,
            category=category,
            search=search,
            author_id=author_id,
            skip=skip,
            limit=limit,
        )
        await self._load_author_names(posts)
        return posts, total

    async def get_post(self, post_id: int) -> BlogPost:
        post = await self.repo.get_by_id(post_id)
        if post is None:
            raise NotFoundException(
                message="文章不存在",
                resource_type="blog_post",
                resource_id=str(post_id),
            )
        await self._load_author_names([post])
        return post

    async def get_post_by_slug(
        self, slug: str, current_user_id: Optional[int] = None
    ) -> BlogPost:
        post = await self.repo.get_by_slug(slug)
        if post is None:
            raise NotFoundException(
                message="文章不存在", resource_type="blog_post", resource_id=slug
            )
        await self._load_author_names([post])
        if current_user_id:
            setattr(
                post,
                "is_liked_by_me",
                (await self.repo.get_like(post.id, current_user_id)) is not None,
            )
        return post

    async def create_post(self, author_id: int, data) -> BlogPost:
        slug = await self._unique_slug(generate_slug(data.title))
        post = await self.repo.create(
            {
                "title": data.title,
                "slug": slug,
                "excerpt": data.excerpt,
                "content_markdown": data.content_markdown,
                "cover_image": data.cover_image,
                "category": data.category,
                "tags": data.tags or [],
                "status": data.status,
                "author_id": author_id,
                "series_id": data.series_id,
                "series_order": data.series_order,
                "published_at": now_utc() if data.status == "published" else None,
            }
        )
        await self.db.commit()
        return post

    async def update_post(
        self, user_id: int, post_id: int, data, is_admin: bool
    ) -> BlogPost:
        post = await self.get_post(post_id)
        if user_id != post.author_id and not is_admin:
            raise AuthorizationException(
                message="无权编辑该文章",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        payload = data.model_dump(exclude_unset=True)
        if "title" in payload and payload["title"] != post.title:
            payload["slug"] = await self._unique_slug(generate_slug(payload["title"]))
        if (
            "status" in payload
            and payload["status"] == "published"
            and post.status != "published"
        ):
            payload["published_at"] = now_utc()
        await self.repo.update(post, payload)
        await self.db.commit()
        return post

    async def publish_post(self, post_id: int) -> BlogPost:
        post = await self.get_post(post_id)
        await self.repo.update(post, {"status": "published", "published_at": now_utc()})
        await self.db.commit()
        return post

    async def archive_post(self, post_id: int) -> BlogPost:
        post = await self.get_post(post_id)
        await self.repo.update(post, {"status": "archived"})
        await self.db.commit()
        return post

    async def delete_post(self, user_id: int, post_id: int, is_admin: bool) -> None:
        post = await self.get_post(post_id)
        if user_id != post.author_id and not is_admin:
            raise AuthorizationException(
                message="无权删除该文章",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        await self.repo.update(post, {"status": "deleted"})
        await self.db.commit()

    async def increment_view(self, post_id: int) -> None:
        await self.repo.increment_view(post_id)
        await self.db.commit()

    async def toggle_like(self, post_id: int, user_id: int) -> dict:
        post = await self.repo.get_by_id(post_id)
        if post is None:
            raise NotFoundException(
                message="文章不存在",
                resource_type="blog_post",
                resource_id=str(post_id),
            )
        existing = await self.repo.get_like(post_id, user_id)
        if existing:
            await self.repo.remove_like(existing)
            count = await self.repo.adjust_post_like_count(post_id, -1)
            liked = False
        else:
            await self.repo.add_like(post_id, user_id)
            count = await self.repo.adjust_post_like_count(post_id, 1)
            liked = True
        await self.db.commit()
        return {"liked": liked, "like_count": count}

    async def has_liked(self, post_id: int, user_id: int) -> bool:
        return (await self.repo.get_like(post_id, user_id)) is not None

    # ------------------------------------------------------------------ 系列

    async def list_series(self) -> list:
        return await self.repo.list_series()

    async def create_series(self, user_id: int, data) -> object:
        slug = await self._unique_series_slug(generate_slug(data.title))
        series = await self.repo.create_series(
            {
                "title": data.title,
                "description": data.description,
                "slug": slug,
                "created_by": user_id,
            }
        )
        await self.db.commit()
        return series

    async def delete_series(self, user_id: int, series_id: int, is_admin: bool) -> None:
        series = await self.repo.get_series(series_id)
        if series is None:
            raise NotFoundException(
                message="系列不存在",
                resource_type="blog_series",
                resource_id=str(series_id),
            )
        if user_id != series.created_by and not is_admin:
            raise AuthorizationException(
                message="无权删除该系列",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        await self.repo.delete_series(series_id)
        await self.db.commit()

    # ------------------------------------------------------------------ 内部

    async def _load_author_names(self, posts: list[BlogPost]) -> None:
        if not posts:
            return
        author_ids = {p.author_id for p in posts}
        users = {
            u.id: u
            for u in (
                await self.db.execute(select(User).where(User.id.in_(author_ids)))
            )
            .scalars()
            .all()
        }
        for post in posts:
            user = users.get(post.author_id)
            setattr(
                post,
                "author_name",
                (user.display_name or user.username) if user else None,
            )

    async def _unique_slug(self, base: str) -> str:
        slug = base
        suffix = 2
        while await self.repo.slug_exists(slug):
            slug = f"{base[: BLOG_LIMITS['SLUG_MAX'] - 3]}-{suffix}"
            suffix += 1
        return slug

    async def _unique_series_slug(self, base: str) -> str:
        slug = base
        suffix = 2
        while await self.repo.series_slug_exists(slug):
            slug = f"{base[: BLOG_LIMITS['SLUG_MAX'] - 3]}-{suffix}"
            suffix += 1
        return slug
