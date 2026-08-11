"""活动域错误码（ErrorCode 演进：业务模块自治）。

由全局 ErrorCode re-export（ErrorCode.Event = EventErrorCode）。
"""


class EventErrorCode:
    """活动（报名 / 签到）错误码。"""

    ALREADY_REGISTERED = "ALREADY_REGISTERED"
    ALREADY_CANCELLED = "ALREADY_CANCELLED"
    FULL = "FULL"  # 活动名额已满
