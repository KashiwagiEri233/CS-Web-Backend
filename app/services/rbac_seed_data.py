"""RBAC 默认权限 / 角色种子数据（纯数据，无 IO）。"""

from __future__ import annotations

from typing import Any, Dict, List

# 系统内置管理员角色名。授予/撤销该角色、或对超级用户做角色变更时，
# 要求操作者是超级用户（见 rbac_assignments._check_privilege_escalation）。
ADMIN_ROLE_NAME = "admin"

# 系统默认权限定义
DEFAULT_PERMISSIONS: List[Dict[str, str]] = [
    # 用户管理权限
    {
        "name": "user:create",
        "resource": "user",
        "action": "create",
        "description": "创建用户",
    },
    {
        "name": "user:read",
        "resource": "user",
        "action": "read",
        "description": "查看用户",
    },
    {
        "name": "user:update",
        "resource": "user",
        "action": "update",
        "description": "更新用户",
    },
    {
        "name": "user:delete",
        "resource": "user",
        "action": "delete",
        "description": "删除用户",
    },
    {
        "name": "user:list",
        "resource": "user",
        "action": "list",
        "description": "列出用户",
    },
    {
        "name": "user:manage_roles",
        "resource": "user",
        "action": "manage_roles",
        "description": "管理用户角色",
    },
    # 角色管理权限
    {
        "name": "role:create",
        "resource": "role",
        "action": "create",
        "description": "创建角色",
    },
    {
        "name": "role:read",
        "resource": "role",
        "action": "read",
        "description": "查看角色",
    },
    {
        "name": "role:update",
        "resource": "role",
        "action": "update",
        "description": "更新角色",
    },
    {
        "name": "role:delete",
        "resource": "role",
        "action": "delete",
        "description": "删除角色",
    },
    {
        "name": "role:list",
        "resource": "role",
        "action": "list",
        "description": "列出角色",
    },
    {
        "name": "role:manage_permissions",
        "resource": "role",
        "action": "manage_permissions",
        "description": "管理角色权限",
    },
    # 权限管理权限
    {
        "name": "permission:create",
        "resource": "permission",
        "action": "create",
        "description": "创建权限",
    },
    {
        "name": "permission:read",
        "resource": "permission",
        "action": "read",
        "description": "查看权限",
    },
    {
        "name": "permission:update",
        "resource": "permission",
        "action": "update",
        "description": "更新权限",
    },
    {
        "name": "permission:delete",
        "resource": "permission",
        "action": "delete",
        "description": "删除权限",
    },
    {
        "name": "permission:list",
        "resource": "permission",
        "action": "list",
        "description": "列出权限",
    },
    # 系统管理权限
    {
        "name": "system:monitor",
        "resource": "system",
        "action": "monitor",
        "description": "系统监控",
    },
    {
        "name": "system:logs",
        "resource": "system",
        "action": "logs",
        "description": "查看系统日志",
    },
    # 异常管理权限
    {
        "name": "exception:read",
        "resource": "exception",
        "action": "read",
        "description": "查看异常日志",
    },
    {
        "name": "exception:resolve",
        "resource": "exception",
        "action": "resolve",
        "description": "标记异常已解决",
    },
    # 密码重置审批（Phase 1 迁移）
    {
        "name": "password_reset:read",
        "resource": "password_reset",
        "action": "read",
        "description": "查看密码重置申请",
    },
    {
        "name": "password_reset:approve",
        "resource": "password_reset",
        "action": "approve",
        "description": "批准/拒绝密码重置申请",
    },
    # 公告（Phase 2 迁移）
    {
        "name": "announcement:read",
        "resource": "announcement",
        "action": "read",
        "description": "查看公告（管理视图）",
    },
    {
        "name": "announcement:create",
        "resource": "announcement",
        "action": "create",
        "description": "创建公告",
    },
    {
        "name": "announcement:update",
        "resource": "announcement",
        "action": "update",
        "description": "更新公告",
    },
    {
        "name": "announcement:delete",
        "resource": "announcement",
        "action": "delete",
        "description": "删除公告",
    },
    # 通知（Phase 2 迁移）
    {
        "name": "notification:read",
        "resource": "notification",
        "action": "read",
        "description": "查看群发记录",
    },
    {
        "name": "notification:create",
        "resource": "notification",
        "action": "create",
        "description": "发送全站/定向通知",
    },
    # 入社申请（Phase 2 迁移）
    {
        "name": "join:read",
        "resource": "join",
        "action": "read",
        "description": "查看入社申请",
    },
    {
        "name": "join:review",
        "resource": "join",
        "action": "review",
        "description": "审批入社申请",
    },
    # 活动（Phase 3 迁移）
    {
        "name": "event:read",
        "resource": "event",
        "action": "read",
        "description": "查看活动（管理视图）",
    },
    {
        "name": "event:create",
        "resource": "event",
        "action": "create",
        "description": "创建活动",
    },
    {
        "name": "event:update",
        "resource": "event",
        "action": "update",
        "description": "编辑活动",
    },
    {
        "name": "event:delete",
        "resource": "event",
        "action": "delete",
        "description": "删除活动",
    },
    {
        "name": "event:batch_update",
        "resource": "event",
        "action": "batch_update",
        "description": "批量更新活动状态",
    },
    {
        "name": "event:registration_manage",
        "resource": "event",
        "action": "registration_manage",
        "description": "管理活动报名",
    },
    {
        "name": "event:checkin_generate",
        "resource": "event",
        "action": "checkin_generate",
        "description": "生成签到码",
    },
    {
        "name": "event:checkin_verify",
        "resource": "event",
        "action": "checkin_verify",
        "description": "现场签到核销",
    },
    {
        "name": "event:settings",
        "resource": "event",
        "action": "settings",
        "description": "管理活动设置",
    },
    # 论坛（Phase 4 迁移）
    {
        "name": "forum:read",
        "resource": "forum",
        "action": "read",
        "description": "查看论坛（管理视图）",
    },
    {
        "name": "forum:update",
        "resource": "forum",
        "action": "update",
        "description": "编辑任意主题/回复",
    },
    {
        "name": "forum:delete",
        "resource": "forum",
        "action": "delete",
        "description": "硬删除主题/回复",
    },
    {
        "name": "forum:hide",
        "resource": "forum",
        "action": "hide",
        "description": "隐藏主题/回复",
    },
    {
        "name": "forum:restore",
        "resource": "forum",
        "action": "restore",
        "description": "恢复主题/回复",
    },
    {
        "name": "forum:pin",
        "resource": "forum",
        "action": "pin",
        "description": "置顶主题",
    },
    {
        "name": "forum:feature",
        "resource": "forum",
        "action": "feature",
        "description": "加精主题",
    },
    {
        "name": "forum:category_create",
        "resource": "forum",
        "action": "category_create",
        "description": "创建版块",
    },
    {
        "name": "forum:category_update",
        "resource": "forum",
        "action": "category_update",
        "description": "编辑版块",
    },
    {
        "name": "forum:category_delete",
        "resource": "forum",
        "action": "category_delete",
        "description": "删除版块",
    },
    # 博客（Phase 4 迁移）
    {
        "name": "blog:update",
        "resource": "blog",
        "action": "update",
        "description": "博客管理（发布/归档/删除任意文章）",
    },
]


def build_default_roles(all_permission_keys: List[str]) -> List[Dict[str, Any]]:
    """根据已解析的权限键列表构造默认角色定义。

    Args:
        all_permission_keys: 形如 ``resource:action`` 的权限键列表（通常为全部权限）。

    Returns:
        角色定义列表，每项含 name / description / is_system / permissions。
        种子角色均为系统内置（is_system=True，禁止删除）。
    """
    return [
        {
            "name": ADMIN_ROLE_NAME,
            "description": "系统管理员，拥有所有权限",
            "is_system": True,
            "permissions": list(all_permission_keys),
        },
        {
            "name": "user_manager",
            "description": "用户管理员，负责管理用户",
            "is_system": True,
            "permissions": [
                "user:create",
                "user:read",
                "user:update",
                "user:list",
                "user:manage_roles",
                "role:read",
                "role:list",
                "permission:read",
                "permission:list",
            ],
        },
        {
            "name": "developer",
            "description": "开发者，可以查看系统信息和API文档",
            "is_system": True,
            "permissions": [
                "user:read",
                "user:list",
                "role:read",
                "role:list",
                "permission:read",
                "permission:list",
                "system:monitor",
                "exception:read",
            ],
        },
        {
            "name": "user",
            "description": "普通用户；仅可使用所有已认证用户共有的接口",
            "is_system": True,
            "permissions": [],
        },
        {
            "name": "guest",
            "description": "访客标签角色；默认不授予业务权限",
            "is_system": True,
            "permissions": [],
        },
        # 细粒度角色（前后端分离迁移 Phase 2 预建；权限随对应模块迁移补充）
        {
            "name": "content_moderator",
            "description": "内容审核员；论坛审核权限随 Phase 4 迁移补充",
            "is_system": True,
            "permissions": [
                "forum:read",
                "forum:update",
                "forum:hide",
                "forum:restore",
                "forum:pin",
                "forum:feature",
            ],
        },
        {
            "name": "exam_admin",
            "description": "考试管理员；考试管理权限随 Phase 5 迁移补充",
            "is_system": True,
            "permissions": [],
        },
        {
            "name": "task_publisher",
            "description": "任务发布员；任务管理权限随 Phase 5 迁移补充",
            "is_system": True,
            "permissions": [],
        },
    ]
