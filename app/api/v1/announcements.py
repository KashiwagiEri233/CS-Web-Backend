"""公告 API：公开生效列表（角色定向）+ 管理员 CRUD。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.dependencies_services import get_announcement_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.announcement import AnnouncementInput, AnnouncementOut
from app.services.announcement_service import AnnouncementService

router = APIRouter()


@router.get("", response_model=list[AnnouncementOut])
async def list_active_announcements(
    request: Request,
    service: AnnouncementService = Depends(get_announcement_service),
) -> Any:
    """生效公告（公开）。带登录态时按角色定向过滤。"""
    # 角色定向：BFF 在登录态下附加 X-User-Roles 头（见前端转发层）
    roles_header = request.headers.get("x-user-roles", "")
    roles = [r.strip() for r in roles_header.split(",") if r.strip()] or None
    return await service.list_active(roles)


@router.get("/admin", response_model=list[AnnouncementOut])
async def list_all_announcements(
    service: AnnouncementService = Depends(get_announcement_service),
    current_user: User = Depends(require_permission("announcement", "read")),
) -> Any:
    """管理员：全部公告。"""
    return await service.list_all()


@router.post("/admin", response_model=AnnouncementOut)
async def create_announcement(
    body: AnnouncementInput,
    service: AnnouncementService = Depends(get_announcement_service),
    current_user: User = Depends(require_permission("announcement", "create")),
) -> Any:
    """管理员：创建公告。"""
    return await service.create(current_user.id, body)


@router.get("/admin/{announcement_id}", response_model=AnnouncementOut)
async def get_announcement(
    announcement_id: int,
    service: AnnouncementService = Depends(get_announcement_service),
    current_user: User = Depends(require_permission("announcement", "read")),
) -> Any:
    """管理员：公告详情。"""
    return await service.get(announcement_id)


@router.patch("/admin/{announcement_id}", response_model=AnnouncementOut)
async def update_announcement(
    announcement_id: int,
    body: AnnouncementInput,
    service: AnnouncementService = Depends(get_announcement_service),
    current_user: User = Depends(require_permission("announcement", "update")),
) -> Any:
    """管理员：更新公告。"""
    return await service.update(announcement_id, body)


@router.delete("/admin/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    service: AnnouncementService = Depends(get_announcement_service),
    current_user: User = Depends(require_permission("announcement", "delete")),
) -> Any:
    """管理员：删除公告。"""
    await service.delete(announcement_id)
    return {"ok": True}


@router.post("/admin/{announcement_id}/toggle", response_model=AnnouncementOut)
async def toggle_announcement(
    announcement_id: int,
    service: AnnouncementService = Depends(get_announcement_service),
    current_user: User = Depends(require_permission("announcement", "update")),
) -> Any:
    """管理员：切换公告激活状态。"""
    return await service.toggle_active(announcement_id)
