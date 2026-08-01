"""社区模块 schema：论坛 / 博客 / 成员 / Feed。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.base import TZModel

# ------------------------------------------------------------------ 论坛

FORUM_LIMITS = {
    "TITLE_MAX": 100,
    "TOPIC_CONTENT_MAX": 10000,
    "REPLY_CONTENT_MAX": 5000,
    "CATEGORY_NAME_MAX": 50,
    "CATEGORY_DESC_MAX": 200,
    "TOPICS_PAGE_SIZE": 20,
    "REPLIES_PAGE_SIZE": 20,
}

SLUG_PATTERN = r"^[a-z0-9-]{1,32}$"
MENTION_PATTERN = r"@([a-zA-Z0-9_-]{3,50})"
VIEW_DEDUP_WINDOW_HOURS = 24


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
        if len(v) > FORUM_LIMITS["CATEGORY_NAME_MAX"]:
            raise ValueError(
                f"版块名称不能超过 {FORUM_LIMITS['CATEGORY_NAME_MAX']} 字符"
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
        if len(v) > FORUM_LIMITS["TITLE_MAX"]:
            raise ValueError(f"标题不能超过 {FORUM_LIMITS['TITLE_MAX']} 字符")
        return v

    @field_validator("content_markdown")
    @classmethod
    def _validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("内容不能为空")
        if len(v) > FORUM_LIMITS["TOPIC_CONTENT_MAX"]:
            raise ValueError(f"内容不能超过 {FORUM_LIMITS['TOPIC_CONTENT_MAX']} 字符")
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
            if len(v) > FORUM_LIMITS["TITLE_MAX"]:
                raise ValueError(f"标题不能超过 {FORUM_LIMITS['TITLE_MAX']} 字符")
        return v

    @field_validator("content_markdown")
    @classmethod
    def _validate_content(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("内容不能为空")
            if len(v) > FORUM_LIMITS["TOPIC_CONTENT_MAX"]:
                raise ValueError(
                    f"内容不能超过 {FORUM_LIMITS['TOPIC_CONTENT_MAX']} 字符"
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
        if len(v) > FORUM_LIMITS["REPLY_CONTENT_MAX"]:
            raise ValueError(f"内容不能超过 {FORUM_LIMITS['REPLY_CONTENT_MAX']} 字符")
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


# ------------------------------------------------------------------ 博客

BLOG_LIMITS = {
    "TITLE_MAX": 120,
    "EXCERPT_MAX": 300,
    "CONTENT_MAX": 50000,
    "TAGS_MAX": 10,
    "TAG_MAX": 30,
    "SLUG_MAX": 80,
}


class BlogPostInput(BaseModel):
    title: str
    content_markdown: str
    excerpt: Optional[str] = None
    cover_image: Optional[str] = None
    category: str = "general"
    tags: Optional[List[str]] = None
    status: str = "draft"  # draft | published | archived
    series_id: Optional[int] = None
    series_order: Optional[int] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        if len(v) > BLOG_LIMITS["TITLE_MAX"]:
            raise ValueError(f"标题不能超过 {BLOG_LIMITS['TITLE_MAX']} 字符")
        return v

    @field_validator("excerpt")
    @classmethod
    def _validate_excerpt(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > BLOG_LIMITS["EXCERPT_MAX"]:
            raise ValueError(f"摘要不能超过 {BLOG_LIMITS['EXCERPT_MAX']} 字符")
        return v

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        if len(v) > BLOG_LIMITS["TAGS_MAX"]:
            raise ValueError(f"标签不能超过 {BLOG_LIMITS['TAGS_MAX']} 个")
        if any(len(t) > BLOG_LIMITS["TAG_MAX"] for t in v):
            raise ValueError(f"单个标签不能超过 {BLOG_LIMITS['TAG_MAX']} 字符")
        return v


class BlogPostOut(BaseModel):
    id: int
    title: str
    slug: str
    excerpt: Optional[str] = None
    content_markdown: str
    cover_image: Optional[str] = None
    category: str
    tags: List[str] = []
    status: str
    author_id: int
    author_name: Optional[str] = None
    series_id: Optional[int] = None
    series_order: Optional[int] = None
    view_count: int
    like_count: int
    published_at: Optional[datetime] = None
    is_liked_by_me: bool = False
    created_at: datetime
    updated_at: datetime


class BlogSeriesInput(BaseModel):
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


class BlogSeriesOut(TZModel):
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
