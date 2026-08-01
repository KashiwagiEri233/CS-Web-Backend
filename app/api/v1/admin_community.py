"""社区管理 API（管理员）：论坛审核/版块 + 博客管理。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request

from app.dependencies_services import get_blog_service, get_forum_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.community import (
    CategoryInput,
    CategoryOut,
    HideRequest,
    TopicOut,
)
from app.services.blog_service import BlogService
from app.services.forum_service import ForumService

router = APIRouter()


def _topic_out(topic) -> dict:
    data = TopicOut.model_validate(topic).model_dump()
    data["author"] = getattr(topic, "author", None)
    data["category"] = getattr(topic, "category", None)
    return data


# ------------------------------------------------------------------ 论坛主题审核


@router.get("/forum/topics")
async def admin_list_topics(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "latest",
    skip: int = 0,
    limit: int = 50,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "read")),
) -> Any:
    """主题列表（管理视图：published + hidden，排除 deleted）。"""
    topics, total = await service.list_topics(
        category_id=category_id,
        search=search,
        status=status,
        sort=sort,
        include_hidden=True,
        skip=skip,
        limit=limit,
    )
    return {"items": [_topic_out(t) for t in topics], "total": total}


@router.put("/forum/topics/{topic_id}", response_model=TopicOut)
async def admin_update_topic(
    topic_id: int,
    body: dict,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "update")),
) -> Any:
    """编辑任意主题（管理员）。"""
    from app.schemas.community import TopicUpdate

    data = TopicUpdate.model_validate(body)
    topic = await service.update_topic(current_user.id, True, topic_id, data)
    return _topic_out(topic)


@router.delete("/forum/topics/{topic_id}")
async def admin_hard_delete_topic(
    topic_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "delete")),
) -> Any:
    """硬删除主题（审计保留）。"""
    await service.hard_delete_topic(current_user.id, topic_id)
    return {"ok": True}


@router.post("/forum/topics/{topic_id}/hide")
async def hide_topic(
    topic_id: int,
    body: HideRequest,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "hide")),
) -> Any:
    await service.hide_topic(current_user.id, topic_id, body.reason)
    return {"ok": True}


@router.post("/forum/topics/{topic_id}/restore")
async def restore_topic(
    topic_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "restore")),
) -> Any:
    await service.restore_topic(current_user.id, topic_id)
    return {"ok": True}


@router.post("/forum/topics/{topic_id}/pin")
async def pin_topic(
    topic_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "pin")),
) -> Any:
    topic = await service.get_topic(topic_id)
    await service.set_topic_pinned(current_user.id, topic_id, not topic.is_pinned)
    return {"ok": True}


@router.post("/forum/topics/{topic_id}/feature")
async def feature_topic(
    topic_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "feature")),
) -> Any:
    topic = await service.get_topic(topic_id)
    await service.set_topic_featured(current_user.id, topic_id, not topic.is_featured)
    return {"ok": True}


# ------------------------------------------------------------------ 论坛回复审核


@router.put("/forum/replies/{reply_id}")
async def admin_update_reply(
    reply_id: int,
    body: dict,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "update")),
) -> Any:
    """编辑任意回复（管理员）。"""
    from app.schemas.community import ReplyInput

    data = ReplyInput.model_validate(body)
    reply = await service.update_reply(
        current_user.id, True, reply_id, data.content_markdown
    )
    return {"id": reply.id, "content_markdown": reply.content_markdown}


@router.delete("/forum/replies/{reply_id}")
async def admin_hard_delete_reply(
    reply_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "delete")),
) -> Any:
    await service.hard_delete_reply(current_user.id, reply_id)
    return {"ok": True}


@router.post("/forum/replies/{reply_id}/hide")
async def hide_reply(
    reply_id: int,
    body: HideRequest,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "hide")),
) -> Any:
    await service.hide_reply(current_user.id, reply_id, body.reason)
    return {"ok": True}


@router.post("/forum/replies/{reply_id}/restore")
async def restore_reply(
    reply_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "restore")),
) -> Any:
    await service.restore_reply(current_user.id, reply_id)
    return {"ok": True}


# ------------------------------------------------------------------ 版块管理


@router.get("/forum/categories", response_model=list[CategoryOut])
async def admin_list_categories(
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "read")),
) -> Any:
    return await service.list_categories()


@router.post("/forum/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryInput,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "category_create")),
) -> Any:
    return await service.create_category(current_user.id, body)


@router.put("/forum/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int,
    body: CategoryInput,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "category_update")),
) -> Any:
    return await service.update_category(current_user.id, category_id, body)


@router.delete("/forum/categories/{category_id}")
async def delete_category(
    category_id: int,
    service: ForumService = Depends(get_forum_service),
    current_user: User = Depends(require_permission("forum", "category_delete")),
) -> Any:
    await service.delete_category(current_user.id, category_id)
    return {"ok": True}


# ------------------------------------------------------------------ 博客管理


@router.post("/blog")
async def admin_blog_action(
    request: Request,
    service: BlogService = Depends(get_blog_service),
    current_user: User = Depends(require_permission("blog", "update")),
) -> Any:
    """博客管理操作：{sub: publish|archive|delete, post_id}。"""
    body = await request.json()
    sub = body.get("sub")
    post_id = body.get("post_id")
    if not post_id:
        return {"error": "缺少 post_id"}
    if sub == "publish":
        return {"post": _post_out(await service.publish_post(int(post_id)))}
    if sub == "archive":
        return {"post": _post_out(await service.archive_post(int(post_id)))}
    if sub == "delete":
        await service.delete_post(current_user.id, int(post_id), is_admin=True)
        return {"ok": True}
    return {"error": "未知操作"}


def _post_out(post) -> dict:
    from app.schemas.community import BlogPostOut

    return BlogPostOut.model_validate(post).model_dump()
