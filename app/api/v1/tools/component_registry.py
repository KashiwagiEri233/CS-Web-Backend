"""组件注册表 API：组件 / 变体 / 迁移状态 / 指南。

TOOLS-GOV Slice D（2026-09-14）：解除最后一个模块级 mypy 忽略指令，路由对齐
service 真实实现——原路由调用 create_variant/update_variant/get_guide 等
service 上不存在的方法（14 端点全 500）。对齐要点：

- 变体开关走 PATCH /variants（前端 BFF 语义，body=variantId/enabled）；
- 迁移状态 PUT /migration-status 返回可见性联动结果（含 visibility_key）；
- 指南只有 upsert 语义（POST /guide → service.update_guide），无独立读取
  （guide/variants 内嵌于 ComponentItemOut，GET /guide 由其派生）；
- 审计依赖走既有 RBAC + audit_logs/api_usage 体系，route 不再传递 audit/meta
  参数（原设计过度，service 层本就不接收）；
- 单个变体 create/update 路由删除（service 无对应写入口，前端无消费方；
  批量写入口 replace_variants 为 service 内部能力）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies_services import get_component_registry_service
from app.middleware.rbac import require_permission
from app.schemas.tools import (
    ComponentGuideInput,
    ComponentItemInput,
    ComponentItemOut,
    ComponentMigrationStatusInput,
    ComponentMigrationStatusOutput,
    ComponentVariantOut,
    ComponentVariantPresetInput,
    ComponentVariantToggleInput,
)
from app.services.component_registry_service import ComponentRegistryService

router = APIRouter()


@router.get("/components", response_model=list[ComponentItemOut])
async def list_components(
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return await service.list_components()


@router.get("/components/{component_id}", response_model=ComponentItemOut)
async def get_component(
    component_id: int,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    return await service.get_component(component_id)


@router.post("/components", response_model=ComponentItemOut, status_code=201)
async def create_component(
    body: ComponentItemInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    _current_user: Any = Depends(require_permission("component", "create")),
) -> Any:
    return await service.create_component(body)


@router.put("/components/{component_id}", response_model=ComponentItemOut)
async def update_component(
    component_id: int,
    body: ComponentItemInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    _current_user: Any = Depends(require_permission("component", "update")),
) -> Any:
    return await service.update_component(component_id, body)


@router.delete("/components/{component_id}")
async def delete_component(
    component_id: int,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    _current_user: Any = Depends(require_permission("component", "delete")),
) -> Any:
    await service.delete_component(component_id)
    return {"ok": True}


# ------------------------------------------------------------------ 变体


@router.get(
    "/components/{component_id}/variants", response_model=list[ComponentVariantOut]
)
async def list_variants(
    component_id: int,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    item = await service.get_component(component_id)
    return item.variants


@router.patch(
    "/components/{component_id}/variants", response_model=list[ComponentVariantOut]
)
async def toggle_variant(
    component_id: int,
    body: ComponentVariantToggleInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    _current_user: Any = Depends(require_permission("component", "update")),
) -> Any:
    return await service.toggle_variant(component_id, body.variant_id, body.enabled)


@router.post(
    "/components/{component_id}/variants/preset",
    response_model=list[ComponentVariantOut],
)
async def apply_variant_preset(
    component_id: int,
    body: ComponentVariantPresetInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    _current_user: Any = Depends(require_permission("component", "update")),
) -> Any:
    return await service.apply_variant_preset(component_id, body.preset)


# ------------------------------------------------------------------ 迁移状态


@router.get(
    "/components/{component_id}/migration-status",
    response_model=ComponentMigrationStatusOutput,
)
async def get_migration_status(
    component_id: int,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    """派生自 ComponentItemOut（service 无独立读取入口；old == current）。"""
    item = await service.get_component(component_id)
    return ComponentMigrationStatusOutput(
        name=item.name,
        old_migration_status=item.migration_status,
        migration_status=item.migration_status,
    )


@router.put(
    "/components/{component_id}/migration-status",
    response_model=ComponentMigrationStatusOutput,
)
async def set_migration_status(
    component_id: int,
    body: ComponentMigrationStatusInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    _current_user: Any = Depends(require_permission("component", "update")),
) -> Any:
    """更新迁移状态；达到 migrated 时联动开放对应可见性模块（service 内闭环）。"""
    result = await service.set_migration_status(component_id, body.migration_status)
    return ComponentMigrationStatusOutput(
        name=result.name,
        old_migration_status=result.old_migration_status,
        migration_status=result.migration_status,
        visibility_opened=result.visibility_opened,
        visibility_key=result.visibility_key,
    )


# ------------------------------------------------------------------ 指南


@router.get("/components/{component_id}/guide")
async def get_guide(
    component_id: int,
    service: ComponentRegistryService = Depends(get_component_registry_service),
) -> Any:
    item = await service.get_component(component_id)
    return item.guide


@router.post("/components/{component_id}/guide", response_model=ComponentItemOut)
async def update_guide(
    component_id: int,
    body: ComponentGuideInput,
    service: ComponentRegistryService = Depends(get_component_registry_service),
    _current_user: Any = Depends(require_permission("component", "update")),
) -> Any:
    """指南 upsert（service 仅有 update_guide；不存在则创建）。"""
    return await service.update_guide(component_id, body)
