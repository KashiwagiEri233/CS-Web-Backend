"""社区 v2 保留域服务（ER-15 Phase 3 后）：分类 / 关注 / 举报 / 系列。

帖子域已迁至 :mod:`app.services.community_post`（PostService）、
评论域已迁至 :mod:`app.services.community_comment`（CommentService）、
互动域已迁至 :mod:`app.services.community_interaction`（Phase 2）、
通知 emit 已迁至 :mod:`app.services.community_notifications`。
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.constants import COMMUNITY_LIMITS
from app.models.community import CommunityReport
from app.models.user import User
from app.repositories.community_repo import (
    CommunityCategoryRepository,
    CommunityCommentRepository,
    CommunityFollowRepository,
    CommunityPostRepository,
    CommunityReportRepository,
    CommunitySeriesRepository,
)
from app.repositories.user_repo import UserRepository
from app.core.events import event_bus
from app.services.community_utils import (
    generate_slug,
    hash_ip_for_view,
)

# ER-15 Phase 0：纯函数已提取至 community_utils，此处 re-export 保持对外
# import 路径兼容（api/v1/community.py 仍可 `from community_service import hash_ip_for_view`）。


class CommunityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.category_repo = CommunityCategoryRepository(db)
        self.post_repo = CommunityPostRepository(db)
        self.comment_repo = CommunityCommentRepository(db)
        self.follow_repo = CommunityFollowRepository(db)
        self.report_repo = CommunityReportRepository(db)
        self.series_repo = CommunitySeriesRepository(db)
        self.user_repo = UserRepository(db)

    # ------------------------------------------------------------------ 分类

    async def list_categories(self) -> list:
        return await self.category_repo.list_all()

    async def get_category(self, category_id: int):
        obj = await self.category_repo.get_by_id(category_id)
        if obj is None:
            raise NotFoundException(
                message="分类不存在",
                resource_type="community_category",
                resource_id=str(category_id),
            )
        return obj

    async def create_category(
        self,
        admin_id: int,
        slug: str,
        name: str,
        description=None,
        icon=None,
        sort_order=0,
    ):
        if await self.category_repo.get_by_slug(slug):
            raise ConflictException(
                message="slug 已存在", error_code=ErrorCode.Community.SLUG_EXISTS
            )
        obj = await self.category_repo.create(
            {
                "slug": slug,
                "name": name,
                "description": description,
                "icon": icon,
                "sort_order": sort_order,
                "created_by": admin_id,
            }
        )
        await self.db.commit()
        return obj

    async def update_category(
        self,
        admin_id: int,
        category_id: int,
        slug: str,
        name: str,
        description: Optional[str],
        icon: Optional[str],
        sort_order: int,
    ):
        obj = await self.get_category(category_id)
        if slug and slug != obj.slug:
            if await self.category_repo.get_by_slug(slug):
                raise ConflictException(
                    message="slug 已存在", error_code=ErrorCode.Community.SLUG_EXISTS
                )
        await self.category_repo.update(
            obj,
            {
                "slug": slug,
                "name": name,
                "description": description,
                "icon": icon,
                "sort_order": sort_order,
            },
        )
        await self.db.commit()
        return obj

    async def delete_category(self, admin_id: int, category_id: int) -> None:
        if not await self.category_repo.delete(category_id):
            raise NotFoundException(
                message="分类不存在",
                resource_type="community_category",
                resource_id=str(category_id),
            )
        await self.db.commit()


    # ------------------------------------------------------------------ 关注

    async def toggle_follow(self, follower_id: int, following_id: int) -> dict:
        if follower_id == following_id:
            raise ConflictException(
                message="不能关注自己",
                error_code=ErrorCode.Validation.VALIDATION_FAILED,
            )
        target = await self.user_repo.get_by_id(following_id)
        if target is None or target.deleted_at is not None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=str(following_id),
            )
        existing = await self.follow_repo.get(follower_id, following_id)
        if existing:
            await self.follow_repo.delete(existing)
            following = False
        else:
            await self.follow_repo.create(follower_id, following_id)
            following = True
            await self._notify_follow(follower_id, target)
        await self.db.commit()
        following_count, follower_count = await self.follow_repo.counts(following_id)
        return {
            "following": following,
            "following_count": following_count,
            "follower_count": follower_count,
        }

    async def is_following(self, follower_id: int, following_id: int) -> bool:
        return (await self.follow_repo.get(follower_id, following_id)) is not None

    async def list_following(
        self,
        user_id: int,
        *,
        current_user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> dict:
        users, total = await self.follow_repo.list_following(
            user_id, skip=skip, limit=limit
        )
        return await self._format_follow_users(users, total, current_user_id)

    async def list_followers(
        self,
        user_id: int,
        *,
        current_user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> dict:
        users, total = await self.follow_repo.list_followers(
            user_id, skip=skip, limit=limit
        )
        return await self._format_follow_users(users, total, current_user_id)

    async def get_follow_counts(self, user_id: int) -> dict:
        following, followers = await self.follow_repo.counts(user_id)
        return {"following": following, "followers": followers}

    async def get_following_ids(self, user_id: int) -> list[int]:
        return await self.follow_repo.list_following_ids(user_id)

    # ------------------------------------------------------------------ 举报

    async def submit_report(
        self,
        reporter_id: int,
        target_type: str,
        target_id: int,
        reason: str,
        detail: Optional[str],
    ) -> CommunityReport:
        if target_type == "post":
            report_target: Any = await self.post_repo.get_by_id(target_id)
        else:
            report_target = await self.comment_repo.get_by_id(target_id)
        if report_target is None:
            raise NotFoundException(
                message="目标不存在",
                resource_type=f"community_{target_type}",
                resource_id=str(target_id),
            )
        report = await self.report_repo.create(
            {
                "reporter_id": reporter_id,
                "target_type": target_type,
                "target_id": target_id,
                "reason": reason,
                "detail": detail,
            }
        )
        await self.db.commit()
        return report

    async def list_reports(
        self, *, status: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityReport], int]:
        return await self.report_repo.list(status=status, skip=skip, limit=limit)

    async def resolve_report(
        self, admin_id: int, report_id: int, status: str
    ) -> CommunityReport:
        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise NotFoundException(
                message="举报不存在",
                resource_type="community_report",
                resource_id=str(report_id),
            )
        await self.report_repo.resolve(report, admin_id, status)
        await self.db.commit()
        return report

    # ------------------------------------------------------------------ 系列

    async def list_series(self) -> list:
        return await self.series_repo.list_all()

    async def create_series(self, user_id: int, title: str, description: Optional[str]):
        slug = await self._unique_series_slug(generate_slug(title))
        series = await self.series_repo.create(
            {
                "title": title,
                "description": description,
                "slug": slug,
                "created_by": user_id,
            }
        )
        await self.db.commit()
        return series

    async def delete_series(self, user_id: int, series_id: int, is_admin: bool) -> None:
        series = await self.series_repo.get_by_id(series_id)
        if series is None:
            raise NotFoundException(
                message="系列不存在",
                resource_type="community_series",
                resource_id=str(series_id),
            )
        if user_id != series.created_by and not is_admin:
            raise AuthorizationException(
                message="无权删除该系列",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        await self.series_repo.delete(series_id)
        await self.db.commit()


    # ------------------------------------------------------------------ 内部

    async def _format_follow_users(
        self, users: list[User], total: int, current_user_id: Optional[int]
    ) -> dict:
        items = []
        user_ids = [u.id for u in users]
        counts_map = await self.follow_repo.bulk_counts(user_ids)
        following_set = (
            await self.follow_repo.bulk_is_following(current_user_id, user_ids)
            if current_user_id
            else set()
        )
        for user in users:
            following_count, follower_count = counts_map.get(user.id, (0, 0))
            items.append(
                {
                    "id": user.id,
                    "display_name": user.display_name,
                    "avatar_url": user.avatar_url,
                    "avatar_type": user.avatar_type or "initial",
                    "bio": user.bio,
                    "tech_tags": user.tech_tags or [],
                    "following_count": following_count,
                    "follower_count": follower_count,
                    "is_following": user.id in following_set,
                }
            )
        return {"items": items, "total": total}


    async def _unique_series_slug(self, base: str) -> str:
        slug = base
        suffix = 2
        while await self.series_repo.slug_exists(slug):
            slug = f"{base[: COMMUNITY_LIMITS['SLUG_MAX'] - 3]}-{suffix}"
            suffix += 1
        return slug


    async def _notify_follow(self, follower_id: int, target: User) -> None:
        try:
            # ER-15 Phase 1：通知改发领域事件（订阅者独立 session 查关注者名并落库）
            event_bus.emit(
                "community.user.followed",
                follower_id=follower_id,
                target_user_id=target.id,
            )
        except Exception:  # noqa: BLE001
            pass
