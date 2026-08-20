"""资源 API：上传 / 审核 / 浏览 / 搜索。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.core.exceptions import ValidationException
from app.dependencies import get_current_active_user
from app.dependencies_services import get_resource_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.tools import ResourceInput, ResourceOut
from app.services.resource_service import ResourceService

router = APIRouter()

RESOURCE_FILE_MAX_SIZE = 50 * 1024 * 1024  # 50MB
_RESOURCE_FILES_DIR = Path("uploads/resources")
_RESOURCE_FILES_DIR.mkdir(parents=True, exist_ok=True)
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,200}$")


def _resource_out(resource) -> dict:
    return ResourceOut.model_validate(resource).model_dump()


@router.get("/resources", response_model=PaginatedResponse[dict])
async def list_resources(
    pagination: PaginationParams = Depends(),
    tag: Optional[str] = None,
    service: ResourceService = Depends(get_resource_service),
) -> Any:
    items, total = await service.list_resources(
        tag=tag,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=[_resource_out(r) for r in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/resources/{resource_id}")
async def get_resource(
    resource_id: int,
    service: ResourceService = Depends(get_resource_service),
) -> Any:
    return _resource_out(await service.get_resource(resource_id))


@router.get("/resources/{resource_id}/download")
async def download_resource(
    resource_id: int,
    service: ResourceService = Depends(get_resource_service),
) -> Any:
    return await service.get_download_url(resource_id)


@router.post("/resources/{resource_id}/rate")
async def rate_resource(
    resource_id: int,
    score: float,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    if not 0 <= score <= 5:
        raise ValidationException("score 必须在 0-5 之间")
    await service.rate_resource(current_user.id, resource_id, score)
    return {"ok": True}


# ------------------------------------------------------------------ 上传


@router.post("/resources/upload", response_model=dict, status_code=201)
async def upload_resource(
    request: Request,
    file: UploadFile = File(...),
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    raw = await file.read()
    if len(raw) > RESOURCE_FILE_MAX_SIZE:
        raise ValidationException("文件超过 50MB 上限")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".zip", ".md"}:
        raise ValidationException("不支持的文件类型")
    if not _FILENAME_RE.match(file.filename or ""):
        raise ValidationException("文件名非法")
    stored = _RESOURCE_FILES_DIR / file.filename
    stored.write_bytes(raw)
    resource = await service.register_upload(
        current_user.id, file.filename, str(stored), len(raw)
    )
    return _resource_out(resource)


# ------------------------------------------------------------------ 管理 / 审核


@router.get("/admin/resources")
async def admin_list_resources(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "read")),
) -> Any:
    items, total = await service.list_resources(status=status, skip=skip, limit=limit)
    return {"items": [_resource_out(r) for r in items], "total": total}


@router.post("/admin/resources", response_model=dict, status_code=201)
async def create_resource(
    body: ResourceInput,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "create")),
) -> Any:
    return _resource_out(await service.create_resource(current_user.id, body))


@router.put("/admin/resources/{resource_id}", response_model=dict)
async def update_resource(
    resource_id: int,
    body: ResourceInput,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "update")),
) -> Any:
    return _resource_out(await service.update_resource(resource_id, body))


@router.delete("/admin/resources/{resource_id}")
async def delete_resource(
    resource_id: int,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "delete")),
) -> Any:
    await service.delete_resource(resource_id)
    return {"ok": True}


@router.post("/admin/resources/{resource_id}/approve", response_model=dict)
async def approve_resource(
    resource_id: int,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "approve")),
) -> Any:
    return _resource_out(await service.approve_resource(resource_id))


@router.post("/admin/resources/{resource_id}/reject", response_model=dict)
async def reject_resource(
    resource_id: int,
    reason: Optional[str] = None,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "reject")),
) -> Any:
    return _resource_out(await service.reject_resource(resource_id, reason))


@router.get("/admin/resources/pending")
async def pending_resources(
    skip: int = 0,
    limit: int = 50,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "read")),
) -> Any:
    items, total = await service.list_resources(
        status="pending", skip=skip, limit=limit
    )
    return {"items": [_resource_out(r) for r in items], "total": total}
