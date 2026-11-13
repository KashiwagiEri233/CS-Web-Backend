"""RBAC 授权域错误码（ErrorCode 演进：业务模块自治）。

由全局 ErrorCode re-export（ErrorCode.Authorization = RbacErrorCode，
命名空间名保持 Authorization），调用方访问 ErrorCode.Authorization.X 不变。
"""


class RbacErrorCode:
    """授权类错误码：权限不足、访问被拒。"""

    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SELF_APPROVE = "SELF_APPROVE"
    # 管理操作保护（与前端 admin 语义对齐）
    FORBIDDEN = "FORBIDDEN"  # 普通管理员不可操作其他管理员
    SELF_DEMOTE = "SELF_DEMOTE"  # 不能修改自己的角色
    SELF_DISABLE = "SELF_DISABLE"  # 不能禁用自己
    SELF_DELETE = "SELF_DELETE"  # 不能删除自己
    ROOT_PROTECTED = "ROOT_PROTECTED"  # 超级管理员账号不可被修改/禁用/删除
    LAST_ADMIN = "LAST_ADMIN"  # 不能降级/禁用/删除最后一个活跃管理员
    # 统一授权边界
    SELF_REVIEW_FORBIDDEN = "SELF_REVIEW_FORBIDDEN"  # 禁止审核/验收自己的任务
    ROLE_ASSIGNMENT_FORBIDDEN = "ROLE_ASSIGNMENT_FORBIDDEN"  # 不可授予受保护角色
    SCOPE_FORBIDDEN = "SCOPE_FORBIDDEN"  # 作用范围越权或与角色不符
    ACCOUNT_ACCESS_DENIED = "ACCOUNT_ACCESS_DENIED"  # 无权访问该账户/资源
