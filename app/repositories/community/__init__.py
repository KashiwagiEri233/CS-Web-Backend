"""社区 v2 仓储子包：categories / posts / comments / reactions / favorites /
views / mentions / follows / reports / series。

搜索基于 PostgreSQL 原生全文检索（GIN + tsvector，Phase 6 已落地）。

各仓储类按职责拆分至同目录子模块，此处统一重新导出以简化调用方 import。
"""

from app.repositories.community.category import CommunityCategoryRepository
from app.repositories.community.comment import CommunityCommentRepository
from app.repositories.community.follow import CommunityFollowRepository
from app.repositories.community.interaction import CommunityInteractionRepository
from app.repositories.community.post import CommunityPostRepository
from app.repositories.community.report import CommunityReportRepository
from app.repositories.community.series import CommunitySeriesRepository

__all__ = [
    "CommunityCategoryRepository",
    "CommunityCommentRepository",
    "CommunityFollowRepository",
    "CommunityInteractionRepository",
    "CommunityPostRepository",
    "CommunityReportRepository",
    "CommunitySeriesRepository",
]
