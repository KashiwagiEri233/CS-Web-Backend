"""RBAC API 包：角色 / 权限只读查询汇总。

P7：角色与权限的写入口已收敛到 ``/admin/roles`` 与 ``/admin/users/{id}/role-bindings``；
本包只保留两端共用的只读查询。对外保持 ``from app.api.v1.rbac import router``。
"""

from fastapi import APIRouter

from .permissions import router as permissions_router
from .queries import router as queries_router
from .roles import router as roles_router

router = APIRouter()
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(queries_router)

__all__ = ["router"]
