"""资源 API：上传 / 审核 / 浏览 / 搜索。

TOOLS-GOV Slice C（2026-09-14）：解除模块级 mypy 忽略指令，路由对齐 service
真实实现——审核改调 ``review_resource``（原 approve_resource/reject_resource 不
存在，必 500）；上传修复 filename 为 None 的崩溃并接通 ``create_resource``（原
register_upload 不存在）；下载接通真实 ``file_url``（原 get_download_url 不存
在）；评分端点因模型无存储列显式降级为 501（待立项）；补齐普通用户提交资源
路由 ``POST /resources``（前端提交表单此前无后端落点）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.exceptions import AuthorizationException, ValidationException
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
_ALLOWED_EXTS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".zip", ".md"}


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


@router.post("/resources", response_model=dict, status_code=201)
async def submit_resource(
    body: ResourceInput,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """普通用户提交资源（入待审核池，由管理员审核）。"""
    return _resource_out(await service.create_resource(current_user.id, body))


@router.get("/resources/{resource_id}/download")
async def download_resource(
    resource_id: int,
    service: ResourceService = Depends(get_resource_service),
) -> Any:
    """返回资源文件地址（仅审核通过且带文件的资源对外开放）。"""
    resource = await service.get_resource(resource_id)
    if resource.status != "approved":
        raise AuthorizationException(message="资源未通过审核，暂不可下载")
    if not resource.file_url:
        raise ValidationException(message="该资源没有可下载文件")
    return {"url": resource.file_url}


# 注：原 POST /resources/{resource_id}/rate 评分端点已于 2026-09-14 删除
# （Resource 模型无评分存储、service 无实现、前端无消费方，此前必 500/501）。
# 评分功能如立项将整包设计（ratings 表 + 迁移 + 聚合 + 前端），见根仓待办 P2-5。


# ------------------------------------------------------------------ 上传


@router.post("/resources/upload", response_model=dict, status_code=201)
async def upload_resource(
    file: UploadFile = File(...),
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """上传文件并创建待审核资源（标题取文件名，file_url 指向存储路径）。"""
    filename = file.filename or ""
    if not filename:
        raise ValidationException(message="缺少文件名")
    raw = await file.read()
    if len(raw) > RESOURCE_FILE_MAX_SIZE:
        raise ValidationException(message="文件超过 50MB 上限")
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise ValidationException(message="不支持的文件类型")
    if not _FILENAME_RE.match(filename):
        raise ValidationException(message="文件名非法")
    stored = _RESOURCE_FILES_DIR / filename
    stored.write_bytes(raw)
    body = ResourceInput(
        title=Path(filename).stem,
        url=str(stored),
        description=f"上传文件 {filename}",
        resource_type="file",
        file_url=str(stored),
    )
    resource = await service.create_resource(current_user.id, body)
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
    return _resource_out(
        await service.review_resource(current_user.id, resource_id, True, None)
    )


@router.post("/admin/resources/{resource_id}/reject", response_model=dict)
async def reject_resource(
    resource_id: int,
    reason: Optional[str] = None,
    service: ResourceService = Depends(get_resource_service),
    current_user: User = Depends(require_permission("resource", "reject")),
) -> Any:
    return _resource_out(
        await service.review_resource(current_user.id, resource_id, False, reason)
    )


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
