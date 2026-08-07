"""社区 v2 API（公开/用户）：posts / comments / reactions / follows / reports / drafts。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundException, ValidationException
from app.core.request_context import get_client_meta
from app.database import get_db
from app.dependencies import get_current_active_user, get_optional_current_user
from app.dependencies_services import get_community_service
from app.models.community import CommunityPost
from app.models.user import User
from app.schemas.community import post_to_dict
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.services.community_service import CommunityService
from app.utils.image_validate import is_valid_image_mime

router = APIRouter()

FORUM_IMAGE_MAX_SIZE = 5 * 1024 * 1024
FORUM_IMAGE_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
FORUM_IMAGE_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
FORUM_IMAGE_FILENAME_RE = re.compile(
    r"^[a-f0-9-]{36}-\d+\.(jpg|jpeg|png|webp|gif)$", re.IGNORECASE
)

_IMAGES_DIR = Path("data") / "forum-images"

POST_KINDS = {"topic", "post"}


def _comment_out(comment) -> dict:
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "author_id": comment.author_id,
        "parent_comment_id": comment.parent_comment_id,
        "content_markdown": comment.content_markdown,
        "status": comment.status,
        "like_count": comment.like_count,
        "reply_count": comment.reply_count,
        "hidden_by": comment.hidden_by,
        "hidden_at": comment.hidden_at,
        "hidden_reason": comment.hidden_reason,
        "author": getattr(comment, "author", None),
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
    }


def _category_out(cat) -> dict:
    return {
        "id": cat.id,
        "slug": cat.slug,
        "name": cat.name,
        "description": cat.description,
        "icon": cat.icon,
        "sort_order": cat.sort_order,
        "post_count": cat.post_count,
        "created_by": cat.created_by,
        "created_at": cat.created_at,
        "updated_at": cat.updated_at,
    }


def _member_out(user, post_count: int = 0) -> dict:
    """用户 → 成员出参（与前端 toMember 字段一一对应）。

    role 由 is_superuser / roles 推导：超级用户 → root，否则取首个显式角色，默认 user。
    """
    if user.is_superuser:
        role = "root"
    elif getattr(user, "roles", None):
        role = user.roles[0].name if user.roles else "user"
    else:
        role = "user"
    return {
        "id": user.id,
        "display_name": user.display_name or user.username,
        "bio": user.bio,
        "avatar_url": user.avatar_url,
        "avatar_type": user.avatar_type or "initial",
        "github_url": user.github_url,
        "website_url": user.website_url,
        "tech_tags": user.tech_tags or [],
        "role": role,
        "joined_at": user.created_at,
        "post_count": post_count,
    }


# ------------------------------------------------------------------ 成员


@router.get("/members")
async def list_members(
    db: AsyncSession = Depends(get_db),
    tag: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = Query("active", pattern="^(active|newest|recent)$"),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """社区成员列表：活跃用户（按发帖数/新近排序），支持 tag / search 过滤。

    - sort=active：按发帖数降序（活跃度）；sort=newest|recent：按加入时间倒序。
    - tag：按 tech_tags 包含过滤；search：按 display_name/username 模糊匹配。
    """
    # 基本条件：未软删除
    conds = [User.deleted_at.is_(None)]

    if tag:
        conds.append(User.tech_tags.contains([tag]))
    if search:
        # 全文检索：search_vector @@ websearch_to_tsquery（GIN 索引加速）
        ts_query = func.websearch_to_tsquery(
            text(f"'{settings.FTS_CONFIG}'"), search.strip()
        )
        conds.append(User.search_vector.op("@@")(ts_query))

    # 活跃用户需关联发帖数；普通排序可直接查用户
    base = select(User).where(*conds)

    if sort == "active":
        stmt = (
            select(User, func.count(CommunityPost.id).label("post_count"))
            .outerjoin(CommunityPost, CommunityPost.author_id == User.id)
            .where(*conds)
            .group_by(User.id)
            .order_by(func.count(CommunityPost.id).desc(), User.created_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        return [_member_out(user, int(pc or 0)) for user, pc in rows]

    order = User.created_at.desc()
    users = (await db.scalars(base.order_by(order).limit(limit))).all()
    return [_member_out(user) for user in users]


# ------------------------------------------------------------------ 分类


@router.get("/forum/categories")
async def list_categories(
    service: CommunityService = Depends(get_community_service),
) -> Any:
    return [_category_out(c) for c in await service.list_categories()]


# ------------------------------------------------------------------ 统一内容（posts）


@router.get("/posts", response_model=PaginatedResponse[dict])
async def list_posts(
    pagination: PaginationParams = Depends(),
    kind: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    category_id: Optional[int] = None,
    tag: Optional[str] = None,
    series_id: Optional[int] = None,
    author_id: Optional[int] = None,
    search: Optional[str] = None,
    sort: str = "latest",
    following: bool = False,
    service: CommunityService = Depends(get_community_service),
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> Any:
    posts, total = await service.list_posts(
        kind=kind,
        status=status,
        category_slug=category,
        category_id=category_id,
        tag=tag,
        series_id=series_id,
        author_id=author_id,
        search=search,
        sort=sort,
        following_only=following,
        current_user_id=current_user.id if current_user else None,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=[post_to_dict(p) for p in posts],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/posts/{post_id}", response_model=dict)
async def get_post(
    post_id: int,
    request: Request,
    service: CommunityService = Depends(get_community_service),
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> Any:
    post = await service.get_post(post_id, current_user.id if current_user else None)
    client_ip = get_client_meta(request).get("ip_address")
    from app.services.community_service import hash_ip_for_view

    await service.increment_view(
        post_id,
        current_user.id if current_user else None,
        hash_ip_for_view(client_ip) if client_ip else None,
    )
    return post_to_dict(post)


@router.get("/posts/slug/{slug}", response_model=dict)
async def get_post_by_slug(
    slug: str,
    request: Request,
    service: CommunityService = Depends(get_community_service),
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> Any:
    post = await service.get_post_by_slug(
        slug, current_user.id if current_user else None
    )
    client_ip = get_client_meta(request).get("ip_address")
    from app.services.community_service import hash_ip_for_view

    await service.increment_view(
        post.id,
        current_user.id if current_user else None,
        hash_ip_for_view(client_ip) if client_ip else None,
    )
    return post_to_dict(post)


@router.post("/posts", response_model=dict, status_code=201)
async def create_post(
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    kind = body.get("kind", "topic")
    if kind not in POST_KINDS:
        raise ValidationException(
            message="kind 必须为 topic / post", error_code="VALIDATION_FAILED"
        )
    post = await service.create_post(
        current_user.id,
        kind,
        title=body.get("title", ""),
        content_markdown=body.get("contentMarkdown", body.get("content_markdown", "")),
        category_id=body.get("categoryId") or body.get("category_id"),
        status=body.get("status", "published"),
        slug=body.get("slug"),
        excerpt=body.get("excerpt"),
        cover_image=body.get("coverImage") or body.get("cover_image"),
        tags=body.get("tags"),
        series_id=body.get("seriesId") or body.get("series_id"),
        series_order=body.get("seriesOrder") or body.get("series_order"),
    )
    return post_to_dict(post)


@router.put("/posts/{post_id}", response_model=dict)
async def update_post(
    post_id: int,
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    is_admin = await _is_admin(service, current_user)
    post = await service.update_post(current_user.id, post_id, body, is_admin)
    return post_to_dict(post)


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    is_admin = await _is_admin(service, current_user)
    await service.delete_post(current_user.id, post_id, is_admin)
    return {"ok": True}


@router.get("/drafts")
async def list_drafts(
    pagination: PaginationParams = Depends(),
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    posts, total = await service.user_drafts(
        current_user.id, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[post_to_dict(p) for p in posts],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


# ------------------------------------------------------------------ 评论


@router.get("/posts/{post_id}/comments", response_model=PaginatedResponse[dict])
async def list_comments(
    post_id: int,
    pagination: PaginationParams = Depends(),
    service: CommunityService = Depends(get_community_service),
) -> Any:
    comments, total = await service.list_comments(
        post_id, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[_comment_out(c) for c in comments],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.post("/posts/{post_id}/comments", response_model=dict, status_code=201)
async def create_comment(
    post_id: int,
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    content = body.get("contentMarkdown", body.get("content_markdown", ""))
    if not content:
        raise ValidationException(
            message="内容不能为空", error_code="VALIDATION_FAILED"
        )
    comment = await service.create_comment(
        current_user.id,
        post_id,
        content,
        body.get("parentCommentId") or body.get("parent_comment_id"),
    )
    return _comment_out(comment)


@router.get("/comments/{comment_id}/nested")
async def list_nested_comments(
    comment_id: int,
    service: CommunityService = Depends(get_community_service),
) -> Any:
    comments = await service.list_nested_comments(comment_id)
    return [_comment_out(c) for c in comments]


@router.put("/comments/{comment_id}", response_model=dict)
async def update_comment(
    comment_id: int,
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    content = body.get("contentMarkdown", body.get("content_markdown", ""))
    is_admin = await _is_admin(service, current_user)
    comment = await service.update_comment(
        current_user.id, is_admin, comment_id, content
    )
    return _comment_out(comment)


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    is_admin = await _is_admin(service, current_user)
    await service.delete_comment(current_user.id, is_admin, comment_id)
    return {"ok": True}


# ------------------------------------------------------------------ 点赞/收藏


@router.post("/reactions")
async def toggle_like(
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    target_type = body.get("targetType", body.get("target_type"))
    target_id = body.get("targetId", body.get("target_id"))
    if target_type not in ("post", "comment") or not target_id:
        raise ValidationException(message="参数不合法", error_code="VALIDATION_FAILED")
    return await service.toggle_like(current_user.id, target_type, int(target_id))


@router.post("/favorites")
async def toggle_favorite(
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    target_id = body.get("targetId", body.get("target_id"))
    if not target_id:
        raise ValidationException(message="参数不合法", error_code="VALIDATION_FAILED")
    return await service.toggle_favorite(current_user.id, int(target_id))


@router.get("/favorites")
async def list_favorites(
    pagination: PaginationParams = Depends(),
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    posts, total = await service.list_user_favorites(
        current_user.id, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[post_to_dict(p) for p in posts],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


# ------------------------------------------------------------------ 关注


@router.post("/follows")
async def toggle_follow(
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    following_id = body.get("followingId", body.get("following_id"))
    if not following_id:
        raise ValidationException(message="参数不合法", error_code="VALIDATION_FAILED")
    return await service.toggle_follow(current_user.id, int(following_id))


@router.get("/follows")
async def list_follows(
    type: str = "following",
    page: int = 1,
    page_size: int = Query(20, alias="pageSize"),
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    skip = (max(1, page) - 1) * page_size
    if type == "followers":
        return await service.list_followers(
            current_user.id, current_user_id=current_user.id, skip=skip, limit=page_size
        )
    return await service.list_following(
        current_user.id, current_user_id=current_user.id, skip=skip, limit=page_size
    )


@router.get("/users/{user_id}/follow-status")
async def follow_status(
    user_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return {
        "is_following": await service.is_following(current_user.id, user_id),
        "counts": await service.get_follow_counts(user_id),
    }


@router.get("/users/{user_id}/follow-counts")
async def follow_counts(
    user_id: int,
    service: CommunityService = Depends(get_community_service),
) -> Any:
    return await service.get_follow_counts(user_id)


# ------------------------------------------------------------------ 举报


@router.post("/reports", response_model=dict, status_code=201)
async def submit_report(
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    target_type = body.get("targetType", body.get("target_type"))
    target_id = body.get("targetId", body.get("target_id"))
    reason = body.get("reason")
    if target_type not in ("post", "comment") or not target_id or not reason:
        raise ValidationException(message="参数不合法", error_code="VALIDATION_FAILED")
    report = await service.submit_report(
        current_user.id, target_type, int(target_id), reason, body.get("detail")
    )
    return {"ok": True, "id": report.id}


# ------------------------------------------------------------------ 系列


@router.get("/blog/series")
async def list_series(
    service: CommunityService = Depends(get_community_service),
) -> Any:
    return await service.list_series()


@router.post("/blog/series", response_model=dict, status_code=201)
async def create_series(
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    title = body.get("title", "")
    if not title:
        raise ValidationException(
            message="标题不能为空", error_code="VALIDATION_FAILED"
        )
    return await service.create_series(current_user.id, title, body.get("description"))


# ------------------------------------------------------------------ 用户数据


@router.get("/forum/users/{user_id}/topics", response_model=PaginatedResponse[dict])
async def list_user_topics(
    user_id: int,
    pagination: PaginationParams = Depends(),
    service: CommunityService = Depends(get_community_service),
) -> Any:
    posts, total = await service.list_posts(
        kind="topic", author_id=user_id, skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=[post_to_dict(p) for p in posts],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/forum/users/{user_id}/replies", response_model=PaginatedResponse[dict])
async def list_user_replies(
    user_id: int,
    pagination: PaginationParams = Depends(),
    service: CommunityService = Depends(get_community_service),
) -> Any:
    comments, total = await service.comment_repo.list_for_author(
        user_id, skip=pagination.skip, limit=pagination.limit
    )
    await service._load_author_summaries(comments)
    return PaginatedResponse(
        items=[_comment_out(c) for c in comments],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


# ------------------------------------------------------------------ 上传


@router.post("/forum/upload")
async def upload_forum_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
) -> Any:
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


# ------------------------------------------------------------------ 内部


async def _is_admin(service: CommunityService, user: User) -> bool:
    from sqlalchemy import select

    from app.models.role import Role

    if user.is_superuser:
        return True
    roles = (
        (
            await service.db.execute(
                select(Role.name).join(Role.users).where(User.id == user.id)
            )
        )
        .scalars()
        .all()
    )
    return "admin" in roles or "content_moderator" in roles
