"""用户域错误码（ErrorCode 演进首批：业务模块自治，预留路径落地）。

设计（见 app/core/exceptions/error_codes.py docstring）：业务错误码在模块内定义
独立命名空间类，由全局 ErrorCode re-export（ErrorCode.User = UserErrorCode），
调用方访问形式保持 ErrorCode.User.X 不变。
"""


class UserErrorCode:
    """用户域错误码。"""

    # 注册/资料冲突（HTTP 409）
    USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
    EMAIL_EXISTS = "EMAIL_EXISTS"
    # 改密（HTTP 401）
    INVALID_CURRENT_PASSWORD = "INVALID_CURRENT_PASSWORD"
    PASSWORD_IN_HISTORY = "PASSWORD_IN_HISTORY"
