"""社区 v2 管理 API：审核（posts/comments）+ 分类 + 举报处理 + 博客管理。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request

from app.dependencies_services import get_community_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.community import post_to_dict
from app.services.community_service import CommunityService

router = APIRouter()


# ------------------------------------------------------------------ 内容审核


@router.get("/forum/topics")
async def admin_list_posts(
    kind: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "latest",
    skip: int = 0,
    limit: int = 50,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "read")),
) -> Any:
    """内容列表（管理视图：published + hidden，排除 deleted）。"""
    posts, total = await service.list_posts(
        kind=kind,
        status=status,
        search=search,
        sort=sort,
        include_hidden=True,
        skip=skip,
        limit=limit,
    )
    return {"items": [post_to_dict(p) for p in posts], "total": total}


@router.put("/forum/topics/{post_id}")
async def admin_update_post(
    post_id: int,
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "update")),
) -> Any:
    post = await service.update_post(current_user.id, post_id, body, is_admin=True)
    return post_to_dict(post)


@router.delete("/forum/topics/{post_id}")
async def admin_hard_delete_post(
    post_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "delete")),
) -> Any:
    await service.hard_delete_post(current_user.id, post_id)
    return {"ok": True}


@router.post("/forum/topics/{post_id}/hide")
async def hide_post(
    post_id: int,
    body: Optional[dict] = None,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "hide")),
) -> Any:
    reason = (body or {}).get("reason")
    await service.hide_post(current_user.id, post_id, reason)
    return {"ok": True}


@router.post("/forum/topics/{post_id}/restore")
async def restore_post(
    post_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "restore")),
) -> Any:
    await service.restore_post(current_user.id, post_id)
    return {"ok": True}


@router.post("/forum/topics/{post_id}/pin")
async def pin_post(
    post_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "pin")),
) -> Any:
    post = await service.get_post(post_id)
    await service.set_post_pinned(current_user.id, post_id, not post.is_pinned)
    return {"ok": True}


@router.post("/forum/topics/{post_id}/feature")
async def feature_post(
    post_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "feature")),
) -> Any:
    post = await service.get_post(post_id)
    await service.set_post_featured(current_user.id, post_id, not post.is_featured)
    return {"ok": True}


@router.put("/forum/replies/{comment_id}")
async def admin_update_comment(
    comment_id: int,
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "update")),
) -> Any:
    content = body.get("contentMarkdown", body.get("content_markdown", ""))
    comment = await service.update_comment(current_user.id, True, comment_id, content)
    return {"id": comment.id, "content_markdown": comment.content_markdown}


@router.delete("/forum/replies/{comment_id}")
async def admin_hard_delete_comment(
    comment_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "delete")),
) -> Any:
    await service.hard_delete_comment(current_user.id, comment_id)
    return {"ok": True}


@router.post("/forum/replies/{comment_id}/hide")
async def hide_comment(
    comment_id: int,
    body: Optional[dict] = None,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "hide")),
) -> Any:
    reason = (body or {}).get("reason")
    await service.hide_comment(current_user.id, comment_id, reason)
    return {"ok": True}


@router.post("/forum/replies/{comment_id}/restore")
async def restore_comment(
    comment_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "restore")),
) -> Any:
    await service.restore_comment(current_user.id, comment_id)
    return {"ok": True}


# ------------------------------------------------------------------ 分类管理


@router.get("/forum/categories")
async def admin_list_categories(
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "read")),
) -> Any:
    return await service.list_categories()


@router.post("/forum/categories", response_model=dict, status_code=201)
async def create_category(
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "category_create")),
) -> Any:
    return await service.create_category(
        current_user.id,
        body.get("slug", ""),
        body.get("name", ""),
        body.get("description"),
        body.get("icon"),
        body.get("sort_order", 0),
    )


@router.put("/forum/categories/{category_id}", response_model=dict)
async def update_category(
    category_id: int,
    body: dict,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "category_update")),
) -> Any:
    return await service.update_category(
        current_user.id,
        category_id,
        body.get("slug", ""),
        body.get("name", ""),
        body.get("description"),
        body.get("icon"),
        body.get("sort_order", 0),
    )


@router.delete("/forum/categories/{category_id}")
async def delete_category(
    category_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "category_delete")),
) -> Any:
    await service.delete_category(current_user.id, category_id)
    return {"ok": True}


# ------------------------------------------------------------------ 举报处理


@router.get("/reports")
async def list_reports(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "read")),
) -> Any:
    reports, total = await service.list_reports(status=status, skip=skip, limit=limit)
    return {
        "items": [
            {
                "id": r.id,
                "reporter_id": r.reporter_id,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "reason": r.reason,
                "detail": r.detail,
                "status": r.status,
                "handled_by": r.handled_by,
                "handled_at": r.handled_at,
                "created_at": r.created_at,
            }
            for r in reports
        ],
        "total": total,
    }


@router.post("/reports/{report_id}/resolve")
async def resolve_report(
    report_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "read")),
) -> Any:
    await service.resolve_report(current_user.id, report_id, "resolved")
    return {"ok": True}


@router.post("/reports/{report_id}/dismiss")
async def dismiss_report(
    report_id: int,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("forum", "read")),
) -> Any:
    await service.resolve_report(current_user.id, report_id, "dismissed")
    return {"ok": True}


# ------------------------------------------------------------------ 博客管理


@router.post("/blog")
async def admin_blog_action(
    request: Request,
    service: CommunityService = Depends(get_community_service),
    current_user: User = Depends(require_permission("blog", "update")),
) -> Any:
    """博客管理操作：{sub: publish|archive|delete, post_id}。"""
    body = await request.json()
    sub = body.get("sub")
    post_id = body.get("post_id")
    if not post_id:
        return {"error": "缺少 post_id"}
    if sub == "publish":
        return {
            "post": post_to_dict(await service.publish_post(current_user.id, int(post_id)))
        }
    if sub == "archive":
        return {
            "post": post_to_dict(await service.archive_post(current_user.id, int(post_id)))
        }
    if sub == "delete":
        await service.delete_post(current_user.id, int(post_id), is_admin=True)
        return {"ok": True}
    return {"error": "未知操作"}
