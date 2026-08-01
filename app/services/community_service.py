"""社区聚合服务：成员名录 + Feed（主题/文章/成员三源合并）。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blog import BlogPost
from app.models.forum import ForumTopic
from app.repositories.community_repo import MemberRepository
from app.services.blog_service import BlogService
from app.services.forum_service import ForumService


class CommunityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.member_repo = MemberRepository(db)
        self.forum_service = ForumService(db)
        self.blog_service = BlogService(db)

    # ------------------------------------------------------------------ 成员

    async def list_members(self, tag: Optional[str] = None) -> list[dict]:
        users = await self.member_repo.list_active(tag)
        return [
            {
                "id": user.id,
                "display_name": user.display_name,
                "bio": user.bio,
                "avatar_url": user.avatar_url,
                "avatar_type": user.avatar_type or "initial",
                "github_url": user.github_url,
                "website_url": user.website_url,
                "tech_tags": user.tech_tags or [],
                "role": _primary_role(user),
                "joined_at": user.created_at,
            }
            for user in users
        ]

    async def list_all_tech_tags(self) -> list[str]:
        return await self.member_repo.list_all_tech_tags()

    # ------------------------------------------------------------------ Feed

    async def get_feed(
        self,
        *,
        kind: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
        exclude_members: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        page = max(1, page)
        page_size = min(50, max(1, page_size))

        topics: list[ForumTopic] = []
        posts: list[BlogPost] = []
        members: list[dict] = []
        if not kind or kind == "topic":
            topics, _ = await self.forum_service.list_topics(limit=100)
        if not kind or kind == "post":
            posts, _ = await self.blog_service.list_posts(status="published", limit=100)
        if (not kind or kind == "member") and not exclude_members:
            members = await self.list_members()

        items: list[dict] = []
        for topic in topics:
            items.append(
                {
                    "kind": "topic",
                    "sort_at": str(topic.last_reply_at or topic.created_at),
                    "data": _topic_to_feed_data(topic),
                }
            )
        for post in posts:
            items.append(
                {
                    "kind": "post",
                    "sort_at": str(post.published_at or post.created_at),
                    "data": _post_to_feed_data(post),
                }
            )
        for member in members:
            items.append(
                {
                    "kind": "member",
                    "sort_at": str(member.get("joined_at") or ""),
                    "data": member,
                }
            )

        if tag:
            t = tag.lower()
            items = [i for i in items if _item_matches_tag(i, t)]
        if search and search.strip():
            q = search.strip().lower()
            items = [i for i in items if _item_matches_search(i, q)]

        items.sort(key=lambda i: i["sort_at"], reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    async def get_feed_tags(self) -> list[dict]:
        tag_map: dict[str, dict] = {}

        topics, _ = await self.forum_service.list_topics(limit=200)
        for topic in topics:
            category = getattr(topic, "category", None)
            if not category or not category.get("name"):
                continue
            entry = tag_map.setdefault(
                category["name"], {"topic_count": 0, "post_count": 0, "member_count": 0}
            )
            entry["topic_count"] += 1

        posts, _ = await self.blog_service.list_posts(status="published", limit=200)
        for post in posts:
            for tag in post.tags or []:
                entry = tag_map.setdefault(
                    tag, {"topic_count": 0, "post_count": 0, "member_count": 0}
                )
                entry["post_count"] += 1
            entry = tag_map.setdefault(
                post.category, {"topic_count": 0, "post_count": 0, "member_count": 0}
            )
            entry["post_count"] += 1

        for tag in await self.list_all_tech_tags():
            entry = tag_map.setdefault(
                tag, {"topic_count": 0, "post_count": 0, "member_count": 0}
            )
            entry["member_count"] = 1

        return sorted(
            [{"tag": k, **v} for k, v in tag_map.items()],
            key=lambda x: -(x["topic_count"] + x["post_count"] + x["member_count"]),
        )

    async def get_feed_stats(self) -> dict:
        _, topic_total = await self.forum_service.list_topics(limit=1)
        _, post_total = await self.blog_service.list_posts(status="published", limit=1)
        members = await self.list_members()
        return {
            "topic_count": topic_total,
            "post_count": post_total,
            "member_count": len(members),
        }


def _primary_role(user) -> str:
    names = {r.name for r in user.roles}
    if user.is_superuser or "root" in names:
        return "root"
    for candidate in ("admin", "content_moderator", "exam_admin", "task_publisher"):
        if candidate in names:
            return candidate
    return "user"


def _topic_to_feed_data(topic: ForumTopic) -> dict:
    return {
        "id": str(topic.id),
        "category_id": str(topic.category_id),
        "author_id": str(topic.author_id),
        "title": topic.title,
        "content_markdown": topic.content_markdown,
        "status": topic.status,
        "is_pinned": topic.is_pinned,
        "is_featured": topic.is_featured,
        "view_count": topic.view_count,
        "reply_count": topic.reply_count,
        "like_count": topic.like_count,
        "favorite_count": topic.favorite_count,
        "last_reply_at": str(topic.last_reply_at) if topic.last_reply_at else None,
        "last_reply_id": str(topic.last_reply_id) if topic.last_reply_id else None,
        "author": getattr(topic, "author", None),
        "category": getattr(topic, "category", None),
        "created_at": str(topic.created_at),
        "updated_at": str(topic.updated_at),
    }


def _post_to_feed_data(post: BlogPost) -> dict:
    return {
        "id": str(post.id),
        "title": post.title,
        "slug": post.slug,
        "excerpt": post.excerpt,
        "content_markdown": post.content_markdown,
        "category": post.category,
        "tags": post.tags or [],
        "status": post.status,
        "author_id": str(post.author_id),
        "author_name": getattr(post, "author_name", None),
        "view_count": post.view_count,
        "like_count": post.like_count,
        "published_at": str(post.published_at) if post.published_at else None,
        "created_at": str(post.created_at),
        "updated_at": str(post.updated_at),
    }


def _item_matches_tag(item: dict, tag: str) -> bool:
    data = item.get("data", {})
    if item["kind"] == "topic":
        category = data.get("category") or {}
        return (
            tag in str(category.get("name", "")).lower()
            or tag in data.get("title", "").lower()
        )
    if item["kind"] == "post":
        return (
            any(tag in str(t).lower() for t in data.get("tags", []))
            or tag in str(data.get("category", "")).lower()
        )
    return any(tag in str(t).lower() for t in data.get("tech_tags", []))


def _item_matches_search(item: dict, q: str) -> bool:
    data = item.get("data", {})
    if item["kind"] == "topic":
        return (
            q in data.get("title", "").lower()
            or q in data.get("content_markdown", "").lower()
        )
    if item["kind"] == "post":
        return (
            q in data.get("title", "").lower()
            or q in str(data.get("excerpt", "")).lower()
        )
    return (
        q in str(data.get("display_name", "")).lower()
        or q in str(data.get("bio", "")).lower()
    )
