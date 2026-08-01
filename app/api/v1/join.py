"""入社申请 API：提交/我的申请 + 管理员列表与审批。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request

from app.core.request_context import get_client_meta
from app.dependencies import get_current_active_user
from app.dependencies_services import get_join_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.join import JoinApplicationInput, JoinApplicationOut, JoinReviewRequest
from app.services.join_service import JoinService

router = APIRouter()


@router.post("", response_model=JoinApplicationOut, status_code=201)
async def submit_application(
    body: JoinApplicationInput,
    request: Request,
    service: JoinService = Depends(get_join_service),
) -> Any:
    """提交入社申请（游客可提交；登录用户由 BFF 附加 X-User-Id 头关联）。"""
    user_id_header = request.headers.get("x-user-id", "")
    user_id = int(user_id_header) if user_id_header.isdigit() else None
    return await service.submit(body, user_id=user_id)


@router.get("/mine", response_model=list[JoinApplicationOut])
async def list_mine(
    service: JoinService = Depends(get_join_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """当前用户的入社申请列表。"""
    return await service.list_mine(current_user.id)


@router.get("/admin", response_model=list[JoinApplicationOut])
async def list_applications(
    status: Optional[str] = None,
    service: JoinService = Depends(get_join_service),
    current_user: User = Depends(require_permission("join", "read")),
) -> Any:
    """管理员：申请列表（status 筛选）。"""
    return await service.list_all(status)


@router.patch("/admin/{application_id}", response_model=JoinApplicationOut)
async def review_application(
    application_id: int,
    body: JoinReviewRequest,
    request: Request,
    service: JoinService = Depends(get_join_service),
    current_user: User = Depends(require_permission("join", "review")),
) -> Any:
    """管理员：审批（approved/rejected）。"""
    return await service.review(
        application_id,
        status=body.status,
        admin_id=current_user.id,
        admin_username=current_user.username,
        review_note=body.review_note,
        client_meta=get_client_meta(request),
    )
