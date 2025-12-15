from fastapi import APIRouter

from app.api.v1 import auth, users, rbac, admin

api_router = APIRouter()

# 注册各个模块的路由
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(users.router, prefix="/users", tags=["用户管理"])
api_router.include_router(rbac.router, prefix="/rbac", tags=["RBAC权限管理"])
api_router.include_router(admin.router, prefix="/admin", tags=["管理后台API"])