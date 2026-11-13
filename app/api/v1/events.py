"""活动 API（用户端）：列表/详情/报名/取消/我的报名。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends

from app.core.exceptions import AuthorizationException, ErrorCode, NotFoundException
from app.dependencies import get_current_active_user, get_optional_current_user
from app.dependencies_services import get_event_service
from app.models.user import User
from app.schemas.event import (
    EventOut,
    EventRegistrationInput,
    EventRegistrationOut,
    event_to_out,
)
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.services.event.event_service import EventService

router = APIRouter()


@router.get("", response_model=PaginatedResponse[EventOut])
async def list_events(
    pagination: PaginationParams = Depends(),
    status: Optional[str] = None,
    search: Optional[str] = None,
    tag: Optional[str] = None,
    service: EventService = Depends(get_event_service),
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> Any:
    """活动列表（status/search/tag 筛选 + 分页，含报名人数）。"""
    events, total = await service.list_events(
        status=status,
        search=search,
        tag=tag,
        user=current_user,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=[event_to_out(e) for e in events],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/me/registered", response_model=list[EventOut])
async def list_registered(
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """当前用户已报名的活动列表。"""
    events = await service.list_user_registered_events(current_user.id)
    return [event_to_out(e) for e in events]


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: int,
    service: EventService = Depends(get_event_service),
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> Any:
    """活动详情（含报名人数）；非公开活动按可见范围校验。"""
    event = await service.get_event(event_id)
    if not await service.user_can_view(current_user, event):
        raise AuthorizationException(
            message="无权查看该活动",
            error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
        )
    return event_to_out(event)


@router.get("/{event_id}/registration", response_model=EventRegistrationOut)
async def get_registration(
    event_id: int,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """当前用户对某活动的报名状态。"""
    reg = await service.get_user_registration(current_user.id, event_id)
    if reg is None:
        raise NotFoundException(
            message="报名记录不存在",
            resource_type="event_registration",
            resource_id=str(event_id),
        )
    return reg


@router.post("/{event_id}/register", response_model=EventRegistrationOut)
async def register_event(
    event_id: int,
    body: EventRegistrationInput,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """报名活动（限额校验；重复报名/名额已满返回 409）。"""
    event = await service.get_event(event_id)
    if not await service.user_can_view(current_user, event):
        raise AuthorizationException(
            message="无权报名该活动",
            error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
        )
    return await service.register(current_user.id, event_id, body.form_data)


@router.delete("/{event_id}/register")
async def cancel_registration(
    event_id: int,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """取消报名。"""
    await service.cancel(current_user.id, event_id)
    return {"ok": True}
