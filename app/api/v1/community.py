"""社区 API（公开/用户）：论坛 / 博客 / 成员 / Feed / 上传。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.exceptions import NotFoundException, ValidationException
from app.core.request_context import get_client_meta
from app.dependencies import get_current_active_user, get_current_user
from app.dependencies_services import (
    get_blog_service,
    get_community_service,
    get_forum_service,
)
from app.models.user import User
from app.schemas.community import (
    BlogPostInput,
    BlogPostOut as BlogPostOutLike,
    BlogSeriesInput,
    CategoryOut,
    FavoriteToggleRequest,
    LikeToggleRequest,
    ReplyInput,
    ReplyOut,
    TopicInput,
    TopicOut,
    TopicUpdate,
)
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.services.blog_service import BlogService
from app.services.community_service import CommunityService
from app.services.forum_service import ForumService
from app.utils.image_validate import is_valid_image_mime

router = APIRouter()

FORUM_IMAGE_MAX_SIZE = 5 * 1024 * 1024
FORUM_IMAGE_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
FORUM_IMAGE_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
FORUM_IMAGE_FILENAME_RE = re.compile(
    r"^[a-f0-9-]{36}-\d+\.(jpg|jpeg|png|webp|gif)$", re.IGNORECASE
)

_IMAGES_DIR = Path("data") / "forum-images"


# ------------------------------------------------------------------ 序列化


def _topic_out(topic) -> dict:
    data = TopicOut.model_validate(topic).model_dump()
    data["author"] = getattr(topic, "author", None)
    data["category"] = getattr(topic, "category", None)
    data["is_liked_by_me"] = getattr(topic, "is_liked_by_me", False)
    data["is_favorited_by_me"] = getattr(topic, "is_favorited_by_me", False)
    return data


def _reply_out(reply) -> dict:
    data = ReplyOut.model_validate(reply).model_dump()
    data["author"] = getattr(reply, "author", None)
    data["is_liked_by_me"] = getattr(reply, "is_liked_by_me", False)
    return data


def _post_out(post) -> dict:
    data = BlogPostOutLike.model_validate(post).model_dump()
    data["author_name"] = getattr(post, "author_name", None)
    data["is_liked_by_me"] = getattr(post, "is_liked_by_me", False)
    return data


# ------------------------------------------------------------------ 论坛


@router.get("/forum/categories", response_model=list[CategoryOut])
async def list_categories(
    service: ForumService = Depends(get_forum_service),
) -> Any:
    return await service.list_categories()


@router.get("/forum/overview")
async def forum_overview(
    service: ForumService = Depends(get_forum_service),
) -> Any:
    """论坛概览：版块 + 各版块最新主题 + 热门主题。"""
    categories = await service.list_categories()
    hot_topics, _ = await service.list_topics(sort="hot", limit=8)
    category_previews = []
    for cat in categories:
        latest, _ = await service.list_topics(
            category_id=cat.id, sort="latest", limit=3
        )
        category_previews.append(
            {**_cat_out(cat), "latestTopics": [_topic_out(t) for t in latest]}
        )
    return {
        "categories": category_previews,
        "hotTopics": [_topic_out(t) for t in hot_topics],
    }


@router.get("/forum/topics", response_model=PaginatedResponse[TopicOut])
async def list_topics(
    pagination: PaginationParams = Depends(),
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    author_id: Optional[int] = None,
    sort: str = "latest",
    service: ForumService = Depends(get_forum_service),
) -> Any:
    topics, total = await service.list_topics(
        category_id=category_id,
        search=search,
        status=status,
        author_id=author_id,
        sort=sort,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=[_topic_out(t) for t in topics],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/forum/topics/{topic_id}", response_model=TopicOut)
async def get_topic(
    topic_id: int,
    request: Request,
    service: ForumService = Depends(get_forum_service),
    current_user: Optional[User] = Depends(get_current_user),
) -> Any:
    """主题详情（含点赞/收藏状态 + 浏览计数）。"""
    topic = await service.get_topic(topic_id, current_user.id if current_user else None)
    ip_hash = None
    client_ip = get_client_meta(request).get("ip_address")
    if client_ip:
        from app.services.forum_service import hash_ip_for_view

        ip_hash = hash_ip_for_view(client_ip)
    await service.record_topic_view(
        topic_id, current_user.id if current_user else None, ip_hash
    )
    return _topic_out(topic)


@router.post("/forum/topics", response_model=TopicOut, status_code=201)
async def create_topic(
    body: TopicInput,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    topic = await service.create_topic(current_user.id, body)
    return _topic_out(topic)


@router.put("/forum/topics/{topic_id}", response_model=TopicOut)
async def update_topic(
    topic_id: int,
    body: TopicUpdate,
    request: Request,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    is_admin = await _is_admin(service.db, current_user)
    topic = await service.update_topic(current_user.id, is_admin, topic_id, body)
    return _topic_out(topic)


@router.delete("/forum/topics/{topic_id}")
async def delete_topic(
    topic_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """作者软删除自己的主题（管理员用硬删除接口）。"""
    is_admin = await _is_admin(service.db, current_user)
    await service.delete_topic(current_user.id, is_admin, topic_id)
    return {"ok": True}


@router.get(
    "/forum/topics/{topic_id}/replies", response_model=PaginatedResponse[ReplyOut]
)
async def list_replies(
    topic_id: int,
    pagination: PaginationParams = Depends(),
    service: ForumService = Depends(get_forum_service),
) -> Any:
    replies, total = await service.list_replies(
        topic_id, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[_reply_out(r) for r in replies],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.post(
    "/forum/topics/{topic_id}/replies", response_model=ReplyOut, status_code=201
)
async def create_reply(
    topic_id: int,
    body: ReplyInput,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    reply = await service.create_reply(current_user.id, topic_id, body)
    return _reply_out(reply)


@router.get("/forum/replies/{reply_id}/nested", response_model=list[ReplyOut])
async def list_nested_replies(
    reply_id: int,
    service: ForumService = Depends(get_forum_service),
) -> Any:
    replies = await service.list_nested_replies(reply_id)
    return [_reply_out(r) for r in replies]


@router.put("/forum/replies/{reply_id}", response_model=ReplyOut)
async def update_reply(
    reply_id: int,
    body: ReplyInput,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    is_admin = await _is_admin(service.db, current_user)
    reply = await service.update_reply(
        current_user.id, is_admin, reply_id, body.content_markdown
    )
    return _reply_out(reply)


@router.delete("/forum/replies/{reply_id}")
async def delete_reply(
    reply_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    is_admin = await _is_admin(service.db, current_user)
    await service.delete_reply(current_user.id, is_admin, reply_id)
    return {"ok": True}


@router.post("/forum/like")
async def toggle_like(
    body: LikeToggleRequest,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.toggle_like(current_user.id, body.target_type, body.target_id)


@router.post("/forum/favorite")
async def toggle_favorite(
    body: FavoriteToggleRequest,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.toggle_favorite(current_user.id, body.topic_id)


@router.get("/forum/favorites", response_model=PaginatedResponse[TopicOut])
async def list_favorites(
    pagination: PaginationParams = Depends(),
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    topics, total = await service.list_user_favorites(
        current_user.id, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[_topic_out(t) for t in topics],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/forum/users/{user_id}/topics", response_model=PaginatedResponse[TopicOut])
async def list_user_topics(
    user_id: int,
    pagination: PaginationParams = Depends(),
    service: ForumService = Depends(get_forum_service),
) -> Any:
    topics, total = await service.list_user_topics(
        user_id, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[_topic_out(t) for t in topics],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/forum/users/{user_id}/replies", response_model=PaginatedResponse[ReplyOut]
)
async def list_user_replies(
    user_id: int,
    pagination: PaginationParams = Depends(),
    service: ForumService = Depends(get_forum_service),
) -> Any:
    replies, total = await service.list_user_replies(
        user_id, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[_reply_out(r) for r in replies],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.post("/forum/upload")
async def upload_forum_image(
    file: UploadFile = File(...),
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """论坛图片上传（≤5MB，JPEG/PNG/WebP/GIF，魔数校验）。"""
    content = await file.read()
    if len(content) > FORUM_IMAGE_MAX_SIZE:
        raise ValidationException(
            message="文件大小不能超过 5MB", error_code="FILE_TOO_LARGE"
        )
    mime = file.content_type or ""
    if mime not in FORUM_IMAGE_ALLOWED_MIME:
        raise ValidationException(
            message="仅支持 JPEG / PNG / WebP / GIF 格式",
            error_code="INVALID_FILE_TYPE",
        )
    ext = Path(file.filename or "").suffix.lower()
    if ext not in FORUM_IMAGE_ALLOWED_EXT:
        raise ValidationException(
            message="文件扩展名不被允许", error_code="INVALID_FILE_TYPE"
        )
    if not is_valid_image_mime(content, mime):
        raise ValidationException(
            message="文件内容与声明类型不匹配", error_code="INVALID_FILE_TYPE"
        )

    _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    import time

    filename = f"{current_user.id}-{int(time.time() * 1000)}{ext}"
    try:
        (_IMAGES_DIR / filename).write_bytes(content)
    except OSError as exc:
        raise ValidationException(
            message="图片保存失败", error_code="FILE_SAVE_FAILED"
        ) from exc
    return {"url": f"/api/community/forum/images/{filename}"}


@router.get("/forum/images/{filename}")
async def serve_forum_image(filename: str) -> Any:
    """论坛图片静态服务（公开）。"""
    if not FORUM_IMAGE_FILENAME_RE.match(filename):
        raise NotFoundException(
            message="图片不存在", resource_type="forum_image", resource_id=filename
        )
    path = _IMAGES_DIR / filename
    if not path.is_file():
        raise NotFoundException(
            message="图片不存在", resource_type="forum_image", resource_id=filename
        )
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return FileResponse(
        path, media_type=mime_map.get(path.suffix.lower(), "application/octet-stream")
    )


# ------------------------------------------------------------------ 博客


@router.get("/blog", response_model=PaginatedResponse[dict])
async def list_blog_posts(
    pagination: PaginationParams = Depends(),
    category: Optional[str] = None,
    search: Optional[str] = None,
    status: str = "published",
    service: BlogService = Depends(get_blog_service),
) -> Any:
    posts, total = await service.list_posts(
        status=status,
        category=category,
        search=search,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=[_post_out(p) for p in posts],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.post("/blog", response_model=dict, status_code=201)
async def create_blog_post(
    body: BlogPostInput,
    service: BlogService = Depends(get_blog_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    post = await service.create_post(current_user.id, body)
    return _post_out(post)


@router.get("/blog/{slug}", response_model=dict)
async def get_blog_post(
    slug: str,
    service: BlogService = Depends(get_blog_service),
    current_user: Optional[User] = Depends(get_current_user),
) -> Any:
    post = await service.get_post_by_slug(
        slug, current_user.id if current_user else None
    )
    await service.increment_view(post.id)
    return _post_out(post)


@router.put("/blog/{slug}", response_model=dict)
async def update_blog_post(
    slug: str,
    body: BlogPostInput,
    service: BlogService = Depends(get_blog_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    post = await service.get_post_by_slug(slug)
    is_admin = await _is_admin(service.db, current_user)
    updated = await service.update_post(current_user.id, post.id, body, is_admin)
    return _post_out(updated)


@router.delete("/blog/{slug}")
async def delete_blog_post(
    slug: str,
    service: BlogService = Depends(get_blog_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    post = await service.get_post_by_slug(slug)
    is_admin = await _is_admin(service.db, current_user)
    await service.delete_post(current_user.id, post.id, is_admin)
    return {"ok": True}


@router.post("/blog/{slug}/like")
async def toggle_blog_like(
    slug: str,
    service: BlogService = Depends(get_blog_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    post = await service.get_post_by_slug(slug)
    return await service.toggle_like(post.id, current_user.id)


@router.get("/blog/series", response_model=list[dict])
async def list_blog_series(
    service: BlogService = Depends(get_blog_service),
) -> Any:
    return await service.list_series()


@router.post("/blog/series", response_model=dict, status_code=201)
async def create_blog_series(
    body: BlogSeriesInput,
    service: BlogService = Depends(get_blog_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.create_series(current_user.id, body)


# ------------------------------------------------------------------ 成员 / Feed


@router.get("/members")
async def list_members(
    tag: Optional[str] = None,
    service: CommunityService = Depends(get_community_service),
) -> Any:
    return await service.list_members(tag)


@router.get("/feed")
async def get_feed(
    kind: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    exclude_members: bool = False,
    page: int = 1,
    page_size: int = 20,
    service: CommunityService = Depends(get_community_service),
) -> Any:
    return await service.get_feed(
        kind=kind,
        tag=tag,
        search=search,
        exclude_members=exclude_members,
        page=page,
        page_size=page_size,
    )


@router.get("/tags")
async def get_tags(
    service: CommunityService = Depends(get_community_service),
) -> Any:
    return {"tags": await service.get_feed_tags()}


@router.get("/feed/stats")
async def get_feed_stats(
    service: CommunityService = Depends(get_community_service),
) -> Any:
    return await service.get_feed_stats()


# ------------------------------------------------------------------ 内部


async def _is_admin(db, user: User) -> bool:
    from sqlalchemy import select

    from app.models.role import Role

    if user.is_superuser:
        return True
    roles = (
        (await db.execute(select(Role.name).join(Role.users).where(User.id == user.id)))
        .scalars()
        .all()
    )
    return "admin" in roles or "content_moderator" in roles


def _cat_out(cat) -> dict:
    return CategoryOut.model_validate(cat).model_dump()
