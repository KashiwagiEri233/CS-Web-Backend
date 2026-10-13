"""向后兼容 shim：实现已迁移至 ``app.repositories.community`` 子包。

C-18 repo 巨型文件拆分第一切片（community_repo.py 712 行 → 7 个子模块）。
调用方 ``from app.repositories.community_repo import XxxRepository`` 继续可用，
待 C-17 服务层改造收口后随调用方 import 路径一并清理本文件。
"""

from app.repositories.community import (
    CommunityCategoryRepository,
    CommunityCommentRepository,
    CommunityFollowRepository,
    CommunityInteractionRepository,
    CommunityPostRepository,
    CommunityReportRepository,
    CommunitySeriesRepository,
)

__all__ = [
    "CommunityCategoryRepository",
    "CommunityCommentRepository",
    "CommunityFollowRepository",
    "CommunityInteractionRepository",
    "CommunityPostRepository",
    "CommunityReportRepository",
    "CommunitySeriesRepository",
]