"""Service 层 Depends 工厂：统一从请求级 AsyncSession 构造 service。

用法::

    from app.dependencies_services import get_user_service

    async def endpoint(svc: UserService = Depends(get_user_service)):
        ...
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.announcement_service import AnnouncementService
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.feature_visibility_service import FeatureVisibilityService
from app.services.auxilio_service import AuxilioService
from app.services.community_category import CategoryService
from app.services.community_comment import CommentService
from app.services.community_feed import FeedService
from app.services.community_interaction import FavoriteService, ReactionService
from app.services.community_post import PostService
from app.services.community_report import ReportService
from app.services.community_series import SeriesService
from app.services.component_registry_service import ComponentRegistryService
from app.services.event_service import EventService
from app.services.exam_service import ExamService
from app.services.exception_service import ExceptionService
from app.services.join_service import JoinService
from app.services.notification_service import NotificationService
from app.services.points_service import PointsService
from app.services.rbac_service import RBACService
from app.services.resource_service import ResourceService
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.services.verification_service import VerificationService


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


def get_announcement_service(db: AsyncSession = Depends(get_db)) -> AnnouncementService:
    return AnnouncementService(db)


def get_notification_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def get_join_service(db: AsyncSession = Depends(get_db)) -> JoinService:
    return JoinService(db)


def get_event_service(db: AsyncSession = Depends(get_db)) -> EventService:
    return EventService(db)


def get_feed_service(db: AsyncSession = Depends(get_db)) -> FeedService:
    return FeedService(db)


def get_category_service(db: AsyncSession = Depends(get_db)) -> CategoryService:
    return CategoryService(db)


def get_report_service(db: AsyncSession = Depends(get_db)) -> ReportService:
    return ReportService(db)


def get_series_service(db: AsyncSession = Depends(get_db)) -> SeriesService:
    return SeriesService(db)


def get_post_service(db: AsyncSession = Depends(get_db)) -> PostService:
    return PostService(db)


def get_comment_service(db: AsyncSession = Depends(get_db)) -> CommentService:
    return CommentService(db)


def get_reaction_service(db: AsyncSession = Depends(get_db)) -> ReactionService:
    return ReactionService(db)


def get_favorite_service(db: AsyncSession = Depends(get_db)) -> FavoriteService:
    return FavoriteService(db)


def get_exam_service(db: AsyncSession = Depends(get_db)) -> ExamService:
    return ExamService(db)


def get_resource_service(db: AsyncSession = Depends(get_db)) -> ResourceService:
    return ResourceService(db)


def get_task_service(db: AsyncSession = Depends(get_db)) -> TaskService:
    return TaskService(db)


def get_points_service(db: AsyncSession = Depends(get_db)) -> PointsService:
    return PointsService(db)


def get_auxilio_service(db: AsyncSession = Depends(get_db)) -> AuxilioService:
    return AuxilioService(db)


def get_component_registry_service(
    db: AsyncSession = Depends(get_db),
) -> ComponentRegistryService:
    return ComponentRegistryService(db)


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    # 注入共享会话的 AuditService：login 的成败审计走独立会话（record 默认行为），
    # create_user_with_audit 的原子审计（record_atomic）需要请求级会话。
    return AuthService(db, audit=AuditService(db))


def get_verification_service(db: AsyncSession = Depends(get_db)) -> VerificationService:
    return VerificationService(db)


def get_rbac_service(db: AsyncSession = Depends(get_db)) -> RBACService:
    return RBACService(db)


def get_exception_service(db: AsyncSession = Depends(get_db)) -> ExceptionService:
    return ExceptionService(db)


def get_audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(db)


def get_feature_visibility_service(
    db: AsyncSession = Depends(get_db),
) -> FeatureVisibilityService:
    return FeatureVisibilityService(db)
