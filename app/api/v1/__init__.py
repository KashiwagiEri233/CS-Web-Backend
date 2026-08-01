from fastapi import APIRouter

from app.api.v1 import (
    admin_events,
    admin_roles,
    admin_users,
    announcements,
    audit,
    auth,
    events,
    exceptions,
    join,
    notifications,
    password_resets,
    profile,
    rbac,
    users,
)
from app.core.config import settings

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(profile.router, tags=["个人资料"])
api_router.include_router(users.router, prefix="/users", tags=["用户管理"])
api_router.include_router(rbac.router, prefix="/rbac", tags=["RBAC权限管理"])
api_router.include_router(exceptions.router, prefix="/exceptions", tags=["异常管理"])
api_router.include_router(audit.router, prefix="/audit", tags=["审计日志"])
api_router.include_router(
    password_resets.router, prefix="/admin/password-resets", tags=["密码重置审批"]
)
api_router.include_router(announcements.router, prefix="/announcements", tags=["公告"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["通知"])
api_router.include_router(join.router, prefix="/join", tags=["入社申请"])
api_router.include_router(
    admin_users.router, prefix="/admin/users", tags=["管理员-用户管理"]
)
api_router.include_router(admin_roles.router, prefix="/admin", tags=["管理员-角色权限"])
api_router.include_router(events.router, prefix="/events", tags=["活动"])
api_router.include_router(
    admin_events.router, prefix="/admin/events", tags=["管理员-活动"]
)

if settings.DEBUG:
    from app.api.v1 import dev_exceptions

    api_router.include_router(dev_exceptions.router, prefix="/test", tags=["异常测试"])
