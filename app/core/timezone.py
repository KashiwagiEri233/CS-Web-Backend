"""统一时区工具。

设计原则（项目"UTC 存储 + 本地展示"约定）：
- **存储层一律 UTC**：数据库列（TIMESTAMP WITH TIME ZONE）、JWT exp、refresh token 过期判断
  全部基于 ``now_utc()``。这保证跨时区多实例部署的语义一致性，是唯一正确的做法。
- **展示层用配置时区**：对外可见的 timestamp（错误响应、日志中的时间戳）通过
  ``utc_to_local()`` 转换为 ``Settings.TIMEZONE`` 指定的时区呈现。
- **默认 UTC 向后兼容**：未配置 TIMEZONE 时行为与改造前完全一致。

使用方式：
    from app.core.timezone import now_utc, now_local, utc_to_local

    # 存储 / 过期判断 / JWT
    created_at = now_utc()

    # 展示
    response_timestamp = now_local()
    display = utc_to_local(stored_utc_datetime)
"""

from datetime import date, datetime, timezone
from typing import Optional

from app.core.config import settings


def now_utc() -> datetime:
    """返回当前 UTC 时间（aware）。

    用于所有存储/过期/JWT 场景，替代散落的 ``datetime.now(timezone.utc)``。
    """
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    """返回当前时间，时区为 ``Settings.TIMEZONE``。

    用于展示层（响应、日志）。
    """
    return datetime.now(settings.tzinfo)


def utc_to_local(dt: Optional[datetime]) -> Optional[datetime]:
    """把 UTC datetime 转换为 ``Settings.TIMEZONE``。

    - None 透传（方便 optional 字段）。
    - naive datetime 视为 UTC（容错旧数据；新增数据应统一 aware）。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(settings.tzinfo)


def local_to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """把本地时区 datetime 转换为 UTC（对称工具，少量场景需要）。

    - None 透传。
    - naive datetime 视为配置时区（``Settings.TIMEZONE``）。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=settings.tzinfo)
    return dt.astimezone(timezone.utc)


def local_day_start_utc(d: Optional[date] = None) -> datetime:
    """配置时区某日（默认今天）的零点，转换为 UTC aware（存储层比较口径）。

    重复实现治理波次 B2：收敛 workbench._local_day_start_utc 与
    auxilio_tool_repo._today_start_utc 的相同实现。
    """
    day = d or now_local().date()
    start = local_to_utc(datetime.combine(day, datetime.min.time()))
    assert start is not None  # 入参恒非 None
    return start


def iso_or_none(dt: Optional[datetime]) -> Optional[str]:
    """datetime → ISO 字符串；None 原样返回（重复实现治理波次 D2 B17）。"""
    return dt.isoformat() if dt else None
