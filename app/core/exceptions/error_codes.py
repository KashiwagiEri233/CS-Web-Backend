"""错误码注册表（类命名空间）。

设计目标：
1. 消除散落在异常类/handler 里的魔法字符串，建立单一事实源。
2. 用类嵌套形成命名空间，IDE 补全友好，零运行时开销。
3. 为第二步"业务模块自治"预留：未来业务错误码可在模块内定义独立命名空间类，
   （如 app/services/user/errors.py: class UserErrorCode: ...），
   只需在 __init__.py re-export，调用方访问方式不变。

命名空间按异常类的层次组织（而非业务模块），因为当前所有异常都定义在 core。
当某个业务异常子类连同其错误码迁移到业务模块时，整块内嵌类一起搬走即可。
"""


class ErrorCode:
    """错误码命名空间根。

    用法：
        raise AuthenticationException(error_code=ErrorCode.Auth.AUTHENTICATION_FAILED)

    访问形式固定为 ErrorCode.<Namespace>.<NAME>，第二步迁移时只是 import 路径
    从 core 扩展到业务模块（业务模块自行 re-export 到全局 ErrorCode 即可）。
    """

    # ---------------- 通用业务 ----------------
    class Business:
        """通用业务错误。"""

        BUSINESS_ERROR = "BUSINESS_ERROR"

    # ---------------- 认证（Authentication，HTTP 401） ----------------
    class Auth:
        """认证类错误码：身份验证失败、凭据无效、账户未激活等。"""

        AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
        INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
        USER_NOT_ACTIVE = "USER_NOT_ACTIVE"
        # 邮箱已注册（冲突场景由 Conflict 命名空间抛出，401 场景复用此码标识枚举）
        TWO_FACTOR_REQUIRED = "TWO_FACTOR_REQUIRED"
        TOTP_INVALID = "TOTP_INVALID"
        # 2FA 状态异常：未初始化 / 已启用 / 已禁用
        TWO_FACTOR_NOT_SETUP = "TWO_FACTOR_NOT_SETUP"
        TWO_FACTOR_ALREADY_ENABLED = "TWO_FACTOR_ALREADY_ENABLED"
        TWO_FACTOR_DISABLED = "TWO_FACTOR_DISABLED"
        # 改密相关
        INVALID_CURRENT_PASSWORD = "INVALID_CURRENT_PASSWORD"
        PASSWORD_IN_HISTORY = "PASSWORD_IN_HISTORY"
        # OAuth
        OAUTH_NOT_CONFIGURED = "OAUTH_NOT_CONFIGURED"
        OAUTH_ERROR = "OAUTH_ERROR"
        OAUTH_STATE_INVALID = "OAUTH_STATE_INVALID"
        OAUTH_STATE_EXPIRED = "OAUTH_STATE_EXPIRED"
        GITHUB_EMAIL_CONFLICT = "GITHUB_EMAIL_CONFLICT"

    # ---------------- 授权（Authorization，HTTP 403） ----------------
    class Authorization:
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
        """资源冲突。"""

        RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
        # 业务子类：用户已存在（未来随 UserAlreadyExistsException 迁到业务模块）
        USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
        EMAIL_EXISTS = "EMAIL_EXISTS"
        # 活动报名（Phase 3 迁移）
        ALREADY_REGISTERED = "ALREADY_REGISTERED"
        ALREADY_CANCELLED = "ALREADY_CANCELLED"
        FULL = "FULL"  # 活动名额已满
        # 社区（Phase 4 迁移）
        SLUG_EXISTS = "SLUG_EXISTS"  # slug 冲突
        STATUS_CONFLICT = "STATUS_CONFLICT"  # 状态不允许该操作（如编辑已删除内容）

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
