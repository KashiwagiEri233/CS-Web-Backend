"""活动管理 API（管理员）：CRUD / 报名管理 / 签到 / 批量 / 统计 / 设置。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request

from app.core.exceptions import ErrorCode, ValidationException
from app.core.request_context import get_client_meta
from app.dependencies_services import get_event_service
from app.middleware.rbac import require_admin_2fa, require_permission
from app.models.user import User
from app.schemas.event import (
    BatchUpdateRequest,
    EventCheckinOut,
    EventInput,
    EventListOut,
    EventOut,
    EventRegistrationOut,
    EventSettingsIn,
)
from app.services.event_service import EventService

router = APIRouter(dependencies=[Depends(require_admin_2fa)])


def _to_event_out(event) -> dict:
    data = EventOut.model_validate(event).model_dump()
    data["registered_count"] = getattr(event, "registered_count", None)
    return data


def _to_registration_out(reg) -> dict:
    return EventRegistrationOut.model_validate(reg).model_dump()


def _bad_request(message: str):
    return ValidationException(
        message=message, error_code=ErrorCode.Validation.VALIDATION_FAILED
    )


# ------------------------------------------------------------------ 活动 CRUD


@router.get("", response_model=EventListOut)
async def list_all_events(
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "read")),
) -> Any:
    """活动列表（管理视图，全部）。

    返回与前端 BFF 期望一致的分页包裹结构：
    { items, total, page, page_size, total_pages }。
    前端 BFF（GET /api/admin/events）按 body.items 解析列表并读取
    body.total / body.total_pages 做分页，裸数组会导致列表永远为空。
    """
    events = await service.event_repo.list_all()
    for event in events:
        setattr(
            event, "registered_count", await service.reg_repo.count_registered(event.id)
        )
    items = [_to_event_out(e) for e in events]
    total = len(items)
    return {
        "items": items,
        "total": total,
        "page": 1,
        "page_size": total,
        "total_pages": 1 if total > 0 else 0,
    }


@router.post("", response_model=EventOut, status_code=201)
async def create_event(
    body: EventInput,
    request: Request,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "create")),
) -> Any:
    """创建活动（广播新活动通知）。"""
    event = await service.create_event(
        current_user.id, body, client_meta=get_client_meta(request)
    )
    return _to_event_out(event)


@router.get("/stats")
async def event_stats(
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "read")),
) -> Any:
    """全部活动报名统计汇总。"""
    return await service.stats_all()


@router.get("/settings")
async def get_event_settings(
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "settings")),
) -> Any:
    """活动设置（含默认值）。"""
    return {"settings": await service.get_settings()}


@router.put("/settings")
async def update_event_settings(
    body: EventSettingsIn,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "settings")),
) -> Any:
    """批量更新活动设置。"""
    return {"settings": await service.update_settings(body)}


@router.delete("/settings")
async def reset_event_setting(
    key: str,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "settings")),
) -> Any:
    """重置单项设置为默认值。"""
    return {"settings": await service.reset_setting(key)}


@router.post("/batch")
async def batch_update_events(
    body: BatchUpdateRequest,
    request: Request,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "batch_update")),
) -> Any:
    """批量更新活动状态。"""
    return await service.batch_update(
        current_user.id,
        body.event_ids,
        body.status or "",
        client_meta=get_client_meta(request),
    )


@router.get("/{event_id}", response_model=EventOut)
async def get_event_detail(
    event_id: int,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "read")),
) -> Any:
    """活动详情（管理视图）。"""
    return _to_event_out(await service.get_event(event_id))


@router.put("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: int,
    body: EventInput,
    request: Request,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "update")),
) -> Any:
    """编辑活动。"""
    event = await service.update_event(
        current_user.id, event_id, body, client_meta=get_client_meta(request)
    )
    return _to_event_out(event)


@router.delete("/{event_id}")
async def delete_event(
    event_id: int,
    request: Request,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "delete")),
) -> Any:
    """删除活动。"""
    await service.delete_event(
        current_user.id, event_id, client_meta=get_client_meta(request)
    )
    return {"ok": True}


# ------------------------------------------------------------------ 报名管理


@router.get("/{event_id}/registrations", response_model=list[EventRegistrationOut])
async def list_registrations(
    event_id: int,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "read")),
) -> Any:
    """活动报名列表。"""
    regs = await service.list_event_registrations(event_id)
    return [_to_registration_out(r) for r in regs]


@router.get("/{event_id}/registrations/stats")
async def registration_stats(
    event_id: int,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "read")),
) -> Any:
    """报名统计（registered/cancelled/waitlisted）。"""
    return await service.registration_stats(event_id)


@router.post("/{event_id}/registrations/manage")
async def manage_registration(
    event_id: int,
    request: Request,
    body: dict = Body(...),
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "registration_manage")),
) -> Any:
    """报名管理：{action: 'add', user_id, form_data?} 或 {action: 'status',
    registration_id, status}。"""
    action = body.get("action")
    if action == "add":
        user_id = body.get("user_id")
        if not user_id:
            raise _bad_request("缺少 user_id")
        reg = await service.admin_add_registration(
            current_user.id,
            int(user_id),
            event_id,
            body.get("form_data"),
            client_meta=get_client_meta(request),
        )
        return _to_registration_out(reg)
    if action == "status":
        registration_id = body.get("registration_id")
        status = body.get("status")
        if not registration_id or status not in {
            "cancelled",
            "waitlisted",
            "registered",
        }:
            raise _bad_request("参数不合法")
        reg = await service.admin_update_registration_status(
            current_user.id,
            int(registration_id),
            status,
            client_meta=get_client_meta(request),
        )
        return _to_registration_out(reg)
    raise _bad_request("action 必须为 add 或 status")


# ------------------------------------------------------------------ 签到


@router.post("/{event_id}/checkin/codes")
async def generate_checkin_codes(
    event_id: int,
    request: Request,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "checkin_generate")),
) -> Any:
    """为已报名用户生成签到码。"""
    return await service.generate_checkin_codes(
        current_user.id, event_id, client_meta=get_client_meta(request)
    )


@router.get("/{event_id}/checkins", response_model=list[EventCheckinOut])
async def list_checkins(
    event_id: int,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "read")),
) -> Any:
    """签到记录列表。"""
    return await service.list_checkins(event_id)


@router.get("/{event_id}/checkins/stats")
async def checkin_stats(
    event_id: int,
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "read")),
) -> Any:
    """签到统计。"""
    return await service.checkin_stats(event_id)


@router.post("/{event_id}/checkin")
async def checkin_by_code(
    event_id: int,
    request: Request,
    body: dict = Body(...),
    service: EventService = Depends(get_event_service),
    current_user: User = Depends(require_permission("event", "checkin_verify")),
) -> Any:
    """现场签到核销（签到码）。"""
    code = body.get("code", "")
    if not code:
        raise _bad_request("缺少签到码")
    return await service.checkin_by_code(
        current_user.id, event_id, str(code), client_meta=get_client_meta(request)
    )
