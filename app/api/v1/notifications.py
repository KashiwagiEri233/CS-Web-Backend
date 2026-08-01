"""站内通知 API：列表/未读数/已读管理 + 管理员广播。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends

from app.dependencies import get_current_active_user
from app.dependencies_services import get_notification_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.notification import BroadcastRequest, NotificationOut
from app.schemas.pagination import PaginationParams, PaginatedResponse
from app.services.notification_service import NotificationService

router = APIRouter()


@router.get("", response_model=PaginatedResponse[NotificationOut])
async def list_notifications(
    pagination: PaginationParams = Depends(),
    is_read: Optional[bool] = None,
    type: Optional[str] = None,
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """当前用户通知列表（分页 + is_read/type 筛选）。"""
    items, total = await service.list_for_user(
        current_user.id,
        is_read=is_read,
        type=type,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/unread-count")
async def unread_count(
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """未读通知数量。"""
    return {"count": await service.unread_count(current_user.id)}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """标记单条已读（须属于当前用户）。"""
    await service.mark_read(current_user.id, notification_id)
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """标记全部已读。"""
    updated = await service.mark_all_read(current_user.id)
    return {"ok": True, "updated": updated}


@router.get("/broadcast-history")
async def broadcast_history(
    limit: int = 20,
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(require_permission("notification", "read")),
) -> Any:
    """管理员：最近群发记录（去重聚合）。"""
    return await service.list_recent_broadcasts(limit)


@router.post("/broadcast")
async def broadcast(
    body: BroadcastRequest,
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(require_permission("notification", "create")),
) -> Any:
    """管理员：发送全站/定向通知。"""
    count = await service.broadcast(
        title=body.title,
        content=body.content,
        sender_id=current_user.id,
        user_ids=body.user_ids,
    )
    return {"ok": True, "sent": count}
