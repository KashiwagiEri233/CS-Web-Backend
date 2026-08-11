"""社区域错误码（ErrorCode 演进：业务模块自治）。

由全局 ErrorCode re-export（ErrorCode.Community = CommunityErrorCode）。
"""


class CommunityErrorCode:
    """社区（posts/comments/reactions）错误码。"""

    SLUG_EXISTS = "SLUG_EXISTS"  # slug 冲突
    STATUS_CONFLICT = "STATUS_CONFLICT"  # 状态不允许该操作（如编辑已删除内容）
