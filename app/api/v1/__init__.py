from fastapi import APIRouter

from app.api.v1 import audit, auth, exceptions, rbac, users
from app.core.config import settings

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(users.router, prefix="/users", tags=["用户管理"])
api_router.include_router(rbac.router, prefix="/rbac", tags=["RBAC权限管理"])
api_router.include_router(exceptions.router, prefix="/exceptions", tags=["异常管理"])
api_router.include_router(audit.router, prefix="/audit", tags=["审计日志"])

if settings.DEBUG:
    from app.api.v1 import test_exceptions

    api_router.include_router(test_exceptions.router, prefix="/test", tags=["异常测试"])
