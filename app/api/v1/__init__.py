from fastapi import APIRouter

from app.api.v1 import (
    admin_community,
    admin_events,
    admin_finance,
    admin_roles,
    admin_tasks,
    admin_users,
    announcements,
    audit,
    auth,
    auxilio,
    community,
    events,
    exceptions,
    join,
    notifications,
    organization,
    password_resets,
    profile,
    rbac,
    search,
    tasks,
    teams,
    tools,
    users,
    wallet,
    workbench,
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
api_router.include_router(community.router, prefix="/community", tags=["社区"])
api_router.include_router(
    admin_community.router, prefix="/admin/community", tags=["管理员-社区"]
)
api_router.include_router(tools.exam.router, prefix="/tools", tags=["考试"])
api_router.include_router(tools.resource.router, prefix="/tools", tags=["资源"])
api_router.include_router(wallet.router, prefix="/wallet", tags=["钱包"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["任务"])
api_router.include_router(tasks.claim_router, prefix="/task-claims", tags=["任务执行"])
api_router.include_router(teams.router, prefix="/teams", tags=["团队"])
api_router.include_router(admin_tasks.router, prefix="/admin", tags=["管理员-任务"])
api_router.include_router(organization.router, prefix="/organization", tags=["组织"])
api_router.include_router(
    organization.admin_router, prefix="/admin/organization", tags=["管理员-组织"]
)
api_router.include_router(
    admin_finance.router, prefix="/admin/finance", tags=["管理员-财务"]
)
api_router.include_router(auxilio.router, tags=["学习助手"])
api_router.include_router(auxilio.analysis_router, prefix="/tools", tags=["学习助手"])
api_router.include_router(
    tools.component_registry.router, prefix="/tools", tags=["组件注册表"]
)
api_router.include_router(workbench.router, tags=["工作台"])
api_router.include_router(tools.feature_visibility.router, tags=["功能模块可见性"])
api_router.include_router(search.router, prefix="/search", tags=["搜索"])

if settings.DEBUG:
    from app.api.v1 import dev_exceptions

    api_router.include_router(dev_exceptions.router, prefix="/test", tags=["异常测试"])
