from app.database import Base
from app.models.user import User, user_roles
from app.models.role import Role, role_permissions
from app.models.permission import Permission
from app.models.refresh_token import RefreshToken
from app.models.exception_log import ExceptionLog
from app.models.audit_log import AuditLog
from app.models.login_history import LoginHistory
from app.models.password_history import PasswordHistory
from app.models.verification_code import VerificationCode
from app.models.password_reset_request import PasswordResetRequest
from app.models.two_factor_auth import TwoFactorAuth
from app.models.setting import Setting
from app.models.resource import Resource
from app.models.component_registry import (
    ComponentRegistryItem,
    ComponentRegistryVariant,
    ComponentRegistryGuide,
)
from app.models.join_application import JoinApplication
from app.models.event import (
    Event,
    EventRegistration,
    EventCheckin,
    ActivityParticipation,
)
from app.models.forum import ForumCategory, ForumTopic, ForumReply
from app.models.forum_interaction import (
    ForumLike,
    ForumFavorite,
    ForumTopicView,
    ForumMention,
)
from app.models.blog import BlogPost, BlogSeries, BlogLike
from app.models.community import (
    CommunityCategory,
    CommunityPost,
    CommunityComment,
    CommunityReaction,
    CommunityFavorite,
    CommunityPostView,
    CommunityMention,
    CommunityFollow,
    CommunityReport,
)
from app.models.notification import Notification, Announcement
from app.models.exam import Exam, ExamQuestion, ExamQuestionOption, ExamAttempt
from app.models.task import Task, TaskClaim
from app.models.points import PointsTransaction

__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "RefreshToken",
    "user_roles",
    "role_permissions",
    "ExceptionLog",
    "AuditLog",
    "LoginHistory",
    "PasswordHistory",
    "VerificationCode",
    "PasswordResetRequest",
    "TwoFactorAuth",
    "Setting",
    "Resource",
    "ComponentRegistryItem",
    "ComponentRegistryVariant",
    "ComponentRegistryGuide",
    "JoinApplication",
    "Event",
    "EventRegistration",
    "EventCheckin",
    "ActivityParticipation",
    "ForumCategory",
    "ForumTopic",
    "ForumReply",
    "ForumLike",
    "ForumFavorite",
    "ForumTopicView",
    "ForumMention",
    "BlogPost",
    "BlogSeries",
    "BlogLike",
    "CommunityCategory",
    "CommunityPost",
    "CommunityComment",
    "CommunityReaction",
    "CommunityFavorite",
    "CommunityPostView",
    "CommunityMention",
    "CommunityFollow",
    "CommunityReport",
    "Notification",
    "Announcement",
    "Exam",
    "ExamQuestion",
    "ExamQuestionOption",
    "ExamAttempt",
    "Task",
    "TaskClaim",
    "PointsTransaction",
]
