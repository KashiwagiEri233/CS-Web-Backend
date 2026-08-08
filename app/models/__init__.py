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
from app.models.community_series import CommunitySeries
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
from app.models.contribution import ContributionCache
from app.models.api_usage import ApiCallLog
from app.models.conversation import Conversation, ChatMessage
from app.models.focus import FocusSession
from app.models.llm_usage import LlmUsageLog
from app.models.llm_config import LlmConfig

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
    "CommunitySeries",
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
    "ContributionCache",
    "ApiCallLog",
    "Conversation",
    "ChatMessage",
    "FocusSession",
    "LlmUsageLog",
    "LlmConfig",
]
