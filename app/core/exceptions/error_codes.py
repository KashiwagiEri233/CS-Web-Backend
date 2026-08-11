"""错误码注册表（类命名空间）。

设计目标：
1. 消除散落在异常类/handler 里的魔法字符串，建立单一事实源。
2. 用类嵌套形成命名空间，IDE 补全友好，零运行时开销。
3. 为第二步"业务模块自治"预留：未来业务错误码可在模块内定义独立命名空间类，
   （如 app/services/user/errors.py: class UserErrorCode: ...），
   只需在 __init__.py re-export，调用方访问方式不变。

命名空间按异常类的层次组织（而非业务模块），因为当前所有异常都定义在 core。
当某个业务异常子类连同其错误码迁移到业务模块时，整块内嵌类一起搬走即可。
已落地域（错误码定义于各 services/*/errors.py，此处 re-export，访问方式不变）：
  - User / Auth / Community / Event / Authorization（rbac）
"""

from app.services.auth.errors import AuthErrorCode
from app.services.community.errors import CommunityErrorCode
from app.services.event.errors import EventErrorCode
from app.services.rbac.errors import RbacErrorCode
from app.services.user.errors import UserErrorCode


class ErrorCode:
    """错误码命名空间根。

    用法：
        raise AuthenticationException(error_code=ErrorCode.Auth.AUTHENTICATION_FAILED)

    访问形式固定为 ErrorCode.<Namespace>.<NAME>，第二步迁移时只是 import 路径
    从 core 扩展到业务模块（业务模块自行 re-export 到全局 ErrorCode 即可）。
    """

    # 业务域（ErrorCode 演进：定义于各 app/services/*/errors.py）
    User = UserErrorCode
    Auth = AuthErrorCode
    Community = CommunityErrorCode
    Event = EventErrorCode
    # 授权域（rbac）：命名空间名保持 Authorization，调用点零改动
    Authorization = RbacErrorCode

    # ---------------- 通用业务 ----------------
    class Business:
        """通用业务错误。"""

        BUSINESS_ERROR = "BUSINESS_ERROR"

    # ---------------- 数据校验（Validation，HTTP 422） ----------------
    class Validation:
        """数据校验失败。"""

        VALIDATION_FAILED = "VALIDATION_FAILED"
        VERIFICATION_CODE_INVALID = "VERIFICATION_CODE_INVALID"
        INVALID_PRESET = "INVALID_PRESET"
        FILE_TOO_LARGE = "FILE_TOO_LARGE"
        INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
        FILE_SAVE_FAILED = "FILE_SAVE_FAILED"
        # 审批流：申请已被处理
        ALREADY_PROCESSED = "ALREADY_PROCESSED"
        ALREADY_REVIEWED = "ALREADY_REVIEWED"
        NO_CHANGE = "NO_CHANGE"  # 状态无变化
        # 默认重置密码未配置
        PASSWORD_RESET_NOT_CONFIGURED = "PASSWORD_RESET_NOT_CONFIGURED"

    # ---------------- 请求本身不合法（HTTP 413 等） ----------------
    class Request:
        """请求层面的拒绝（与请求体内容无关，在解析前就被拦下）。"""

        REQUEST_BODY_TOO_LARGE = "REQUEST_BODY_TOO_LARGE"

    # ---------------- 资源查找（HTTP 404） ----------------
    class NotFound:
        """资源未找到。"""

        RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

    # ---------------- 资源冲突（HTTP 409） ----------------
    class Conflict:
        """资源冲突（通用；活动/社区域码已迁至 Event/Community 命名空间）。"""

        RESOURCE_CONFLICT = "RESOURCE_CONFLICT"

    # ---------------- 数据库（HTTP 500） ----------------
    class Database:
        """数据库相关错误。"""

        DATABASE_ERROR = "DATABASE_ERROR"
        DATABASE_INTEGRITY_ERROR = "DATABASE_INTEGRITY_ERROR"

    # ---------------- 外部服务（HTTP 502） ----------------
    class ExternalService:
        """外部服务调用失败。"""

        EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"

    # ---------------- 限流（HTTP 429） ----------------
    class RateLimit:
        """请求频率超限。"""

        RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # ---------------- 兜底/系统级 ----------------
    class System:
        """系统级兜底错误码。"""

        INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
