"""RBAC API 包：角色 / 权限 / 分配 / 查询 子路由汇总。

对外保持 ``from app.api.v1.rbac import router`` 与
``app.api.v1 import rbac; rbac.router`` 可用。
"""

from fastapi import APIRouter

from .assignments import router as assignments_router
from .permissions import router as permissions_router
from .queries import router as queries_router
from .roles import router as roles_router

router = APIRouter()
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(assignments_router)
router.include_router(queries_router)

__all__ = ["router"]
