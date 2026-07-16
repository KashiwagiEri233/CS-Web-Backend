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
]


def build_default_roles(all_permission_keys: List[str]) -> List[Dict[str, Any]]:
    """根据已解析的权限键列表构造默认角色定义。

    Args:
        all_permission_keys: 形如 ``resource:action`` 的权限键列表（通常为全部权限）。

    Returns:
        角色定义列表，每项含 name / description / permissions。
    """
    return [
        {
            "name": ADMIN_ROLE_NAME,
            "description": "系统管理员，拥有所有权限",
            "permissions": list(all_permission_keys),
        },
        {
            "name": "user_manager",
            "description": "用户管理员，负责管理用户",
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
            "permissions": [],
        },
        {
            "name": "guest",
            "description": "访客标签角色；默认不授予业务权限",
            "permissions": [],
        },
    ]
