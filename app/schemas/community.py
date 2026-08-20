"""社区模块 schema：社区 / 社区 / 成员 / Feed。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.base import TZModel
from app.core.constants import COMMUNITY_LIMITS, MENTION_PATTERN

# ------------------------------------------------------------------ 社区

SLUG_PATTERN = r"^[a-z0-9-]{1,32}$"


class CategoryInput(BaseModel):
    slug: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        import re

        if not re.match(SLUG_PATTERN, v):
            raise ValueError("slug 只能包含小写字母、数字和短横线，长度 1-32")
        return v

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("版块名称不能为空")
        if len(v) > COMMUNITY_LIMITS["CATEGORY_NAME_MAX"]:
            raise ValueError(
                f"版块名称不能超过 {COMMUNITY_LIMITS['CATEGORY_NAME_MAX']} 字符"
            )
        return v


class CategoryOut(TZModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int
    topic_count: int
    post_count: int
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class TopicInput(BaseModel):
    category_id: int
    title: str
    content_markdown: str
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        if len(v) > COMMUNITY_LIMITS["TITLE_MAX"]:
            raise ValueError(f"标题不能超过 {COMMUNITY_LIMITS['TITLE_MAX']} 字符")
        return v

    @field_validator("content_markdown")
    @classmethod
    def _validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("内容不能为空")
        if len(v) > COMMUNITY_LIMITS["TOPIC_CONTENT_MAX"]:
            raise ValueError(
                f"内容不能超过 {COMMUNITY_LIMITS['TOPIC_CONTENT_MAX']} 字符"
            )
        return v


class TopicUpdate(BaseModel):
    title: Optional[str] = None
    content_markdown: Optional[str] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("标题不能为空")
            if len(v) > COMMUNITY_LIMITS["TITLE_MAX"]:
                raise ValueError(f"标题不能超过 {COMMUNITY_LIMITS['TITLE_MAX']} 字符")
        return v

    @field_validator("content_markdown")
    @classmethod
    def _validate_content(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("内容不能为空")
            if len(v) > COMMUNITY_LIMITS["TOPIC_CONTENT_MAX"]:
                raise ValueError(
                    f"内容不能超过 {COMMUNITY_LIMITS['TOPIC_CONTENT_MAX']} 字符"
                )
        return v


class AuthorSummaryOut(BaseModel):
    id: int
    email: str = ""
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_type: str = "initial"


class CategorySummaryOut(BaseModel):
    id: int
    slug: str
    name: str


class TopicOut(BaseModel):
    """主题出参（列表项/详情共用）。"""

    id: int
    category_id: int
    author_id: int
    title: str
    content_markdown: str
    status: str
    is_pinned: bool
    is_featured: bool
    view_count: int
    reply_count: int
    like_count: int
    favorite_count: int
    last_reply_at: Optional[datetime] = None
    last_reply_id: Optional[int] = None
    hidden_by: Optional[int] = None
    hidden_at: Optional[datetime] = None
    hidden_reason: Optional[str] = None
    author: Optional[AuthorSummaryOut] = None
    category: Optional[CategorySummaryOut] = None
    is_liked_by_me: bool = False
    is_favorited_by_me: bool = False
    created_at: datetime
    updated_at: datetime


class ReplyInput(BaseModel):
    content_markdown: str
    parent_reply_id: Optional[int] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("content_markdown")
    @classmethod
    def _validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("内容不能为空")
        if len(v) > COMMUNITY_LIMITS["REPLY_CONTENT_MAX"]:
            raise ValueError(
                f"内容不能超过 {COMMUNITY_LIMITS['REPLY_CONTENT_MAX']} 字符"
            )
        return v


class ReplyOut(BaseModel):
    id: int
    topic_id: int
    author_id: int
    parent_reply_id: Optional[int] = None
    content_markdown: str
    status: str
    like_count: int
    reply_count: int
    hidden_by: Optional[int] = None
    hidden_at: Optional[datetime] = None
    hidden_reason: Optional[str] = None
    author: Optional[AuthorSummaryOut] = None
    is_liked_by_me: bool = False
    created_at: datetime
    updated_at: datetime


class LikeToggleRequest(BaseModel):
    target_type: str  # topic | reply
    target_id: int

    @field_validator("target_type")
    @classmethod
    def _validate_target(cls, v: str) -> str:
        if v not in {"topic", "reply"}:
            raise ValueError("targetType 必须为 topic 或 reply")
        return v


class FavoriteToggleRequest(BaseModel):
    topic_id: int


class HideRequest(BaseModel):
    reason: Optional[str] = None


# ------------------------------------------------------------------ 社区


class CommunitySeriesInput(BaseModel):
    title: str
    description: Optional[str] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v


class CommunitySeriesOut(TZModel):
    id: int
    title: str
    description: Optional[str] = None
    slug: str
    created_by: int
    created_at: datetime


# ------------------------------------------------------------------ 成员 / Feed


class MemberOut(BaseModel):
    id: int
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_type: str = "initial"
    github_url: Optional[str] = None
    website_url: Optional[str] = None
    tech_tags: List[str] = []
    role: str = "user"
    joined_at: Optional[datetime] = None


class FeedItemOut(BaseModel):
    kind: str  # topic | post | member
    sort_at: str
    data: Dict[str, Any]


class FeedTagOut(BaseModel):
    tag: str
    topic_count: int = 0
    post_count: int = 0
    member_count: int = 0


class FeedStatsOut(BaseModel):
    topic_count: int
    post_count: int
    member_count: int


# ------------------------------------------------------- ORM → dict 序列化（路由层共享）


def post_to_dict(post) -> Dict[str, Any]:
    """将 CommunityPost ORM 对象序列化为 API 响应 dict。

    公开接口（app/api/v1/community.py）与管理接口（app/api/v1/admin_community.py）
    共用此单一实现，避免两处 ``_post_out`` 复制漂移。

    ``post`` 可能携带运行时附加属性（``author`` / ``category`` /
    ``is_liked_by_me`` / ``is_favorited_by_me``），用 ``getattr`` 安全读取，
    缺失时回退默认值。
    """
    return {
        "id": post.id,
        "kind": post.kind,
        "category_id": post.category_id,
        "author_id": post.author_id,
        "title": post.title,
        "content_markdown": post.content_markdown,
        "status": post.status,
        "is_pinned": post.is_pinned,
        "is_featured": post.is_featured,
        "reply_count": post.reply_count,
        "favorite_count": post.favorite_count,
        "last_reply_at": post.last_reply_at,
        "last_reply_id": getattr(post, "last_reply_id", None),
        "hidden_by": post.hidden_by,
        "hidden_at": post.hidden_at,
        "hidden_reason": post.hidden_reason,
        "slug": post.slug,
        "excerpt": post.excerpt,
        "cover_image": post.cover_image,
        "tags": post.tags or [],
        "series_id": post.series_id,
        "series_order": getattr(post, "series_order", None),
        "published_at": post.published_at,
        "view_count": post.view_count,
        "like_count": post.like_count,
        "author": getattr(post, "author", None),
        "category": getattr(post, "category", None),
        "is_liked_by_me": getattr(post, "is_liked_by_me", False),
        "is_favorited_by_me": getattr(post, "is_favorited_by_me", False),
        "created_at": post.created_at,
        "updated_at": post.updated_at,
    }
