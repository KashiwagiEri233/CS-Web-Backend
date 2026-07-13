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

    # ---------------- 授权（Authorization，HTTP 403） ----------------
    class Authorization:
        """授权类错误码：权限不足、访问被拒。"""

        AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
        PERMISSION_DENIED = "PERMISSION_DENIED"

    # ---------------- 数据校验（Validation，HTTP 422） ----------------
    class Validation:
        """数据校验失败。"""

        VALIDATION_FAILED = "VALIDATION_FAILED"

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
