"""组件注册表 API：组件 / 变体 / 迁移状态 / 指南 + 审计。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request

from app.core.request_context import get_client_meta
from app.dependencies_services import get_audit_service, get_component_registry_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.tools import (
    ComponentGuideInput,
    ComponentItemInput,
    ComponentMigrationStatusInput,
    ComponentMigrationStatusOutput,
    ComponentVariantInput,
    ComponentVariantPresetInput,
    ComponentVariantToggleInput,
)
from app.services.audit_service import AuditService
from app.services.component_registry_service import ComponentRegistryService

router = APIRouter()


@router.get("/components")
async def list_components(
    q: Optional[str] = None,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return await service.list_components(q)


@router.get("/components/{component_id}")
async def get_component(
    component_id: str,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return await service.get_component(component_id)


@router.post("/components")
async def create_component(
    body: ComponentItemInput,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "create")),
) -> Any:
    meta = get_client_meta(request)
    return await service.create_component(body, current_user.id, meta, audit)


@router.put("/components/{component_id}")
async def update_component(
    component_id: str,
    body: ComponentItemInput,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "update")),
) -> Any:
    meta = get_client_meta(request)
    return await service.update_component(
        component_id, body, current_user.id, meta, audit
    )


@router.delete("/components/{component_id}")
async def delete_component(
    component_id: str,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "delete")),
) -> Any:
    meta = get_client_meta(request)
    await service.delete_component(component_id, current_user.id, meta, audit)
    return {"ok": True}


# ------------------------------------------------------------------ 变体


@router.get("/components/{component_id}/variants")
async def list_variants(
    component_id: str,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return await service.list_variants(component_id)


@router.post("/components/{component_id}/variants")
async def create_variant(
    component_id: str,
    body: ComponentVariantInput,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "update")),
) -> Any:
    meta = get_client_meta(request)
    return await service.create_variant(
        component_id, body, current_user.id, meta, audit
    )


@router.put("/components/{component_id}/variants/{variant_id}")
async def update_variant(
    component_id: str,
    variant_id: str,
    body: ComponentVariantInput,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "update")),
) -> Any:
    meta = get_client_meta(request)
    return await service.update_variant(
        component_id, variant_id, body, current_user.id, meta, audit
    )


@router.post("/components/{component_id}/variants/toggle")
async def toggle_variant(
    component_id: str,
    body: ComponentVariantToggleInput,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "update")),
) -> Any:
    meta = get_client_meta(request)
    return await service.toggle_variant(
        component_id, body, current_user.id, meta, audit
    )


@router.post("/components/{component_id}/variants/preset")
async def apply_preset(
    component_id: str,
    body: ComponentVariantPresetInput,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "update")),
) -> Any:
    meta = get_client_meta(request)
    return await service.apply_preset(component_id, body, current_user.id, meta, audit)


# ------------------------------------------------------------------ 迁移状态


@router.get("/components/{component_id}/migration-status")
async def get_migration_status(
    component_id: str,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return ComponentMigrationStatusOutput.model_validate(
        await service.get_migration_status(component_id)
    )


@router.put("/components/{component_id}/migration-status")
async def set_migration_status(
    component_id: str,
    body: ComponentMigrationStatusInput,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "update")),
) -> Any:
    meta = get_client_meta(request)
    return await service.set_migration_status(
        component_id, body, current_user.id, meta, audit
    )


# ------------------------------------------------------------------ 指南


@router.get("/components/{component_id}/guide")
async def get_guide(
    component_id: str,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return await service.get_guide(component_id)


@router.post("/components/{component_id}/guide")
async def create_guide(
    component_id: str,
    body: ComponentGuideInput,
    request: Request,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("component", "update")),
) -> Any:
    meta = get_client_meta(request)
    return await service.create_guide(component_id, body, current_user.id, meta, audit)
