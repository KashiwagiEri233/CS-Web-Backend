"""异常日志统计查询（从 ExceptionLogRepository 抽出的只读聚合）。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.exception_log import ExceptionLog

# 各维度返回条数上限（by_status_code 不限：HTTP 状态码本就是有限小集合）
_TOP_N = 10


def _top(
    counts: List[Tuple[Any, int]], limit: Optional[int] = _TOP_N
) -> Dict[Any, int]:
    """按计数降序取前 N 项，丢弃空键。"""
    ranked = sorted(
        (item for item in counts if item[0] is not None),
        key=lambda item: item[1],
        reverse=True,
    )
    if limit is not None:
        ranked = ranked[:limit]
    return dict(ranked)


async def fetch_exception_statistics(
    db: AsyncSession, time_window_hours: int = 24
) -> Dict[str, Any]:
    """按时间窗口聚合异常日志统计。

    实现说明：用 ``GROUP BY GROUPING SETS`` 把「总数 + 4 个维度的分组计数」压成
    **一次表扫描**。原实现是 5 条独立查询，每条都在同一时间窗上重新扫一遍表——
    异常表一大，这个运维端点会明显变慢。

    代价：各维度的 top-N 截断改到 Python 侧（GROUPING SETS 无法对单个分组集分别
    LIMIT）。传输行数 = 各维度基数之和，相比多扫 4 遍表仍然划算。

    Args:
        db: 异步会话。
        time_window_hours: 统计窗口（小时）。

    Returns:
        含 total / by_type / by_error_code / by_status_code / by_user 的字典。
    """
    cutoff_time = now_utc() - timedelta(hours=time_window_hours)

    # 每行只属于一个分组集，非本组的维度列为 NULL。
    # GROUPING(col) = 0 表示该列参与了本行分组，1 表示被汇总掉——用它区分
    # "这一行是按该列分的组" 与 "该列本身的值就是 NULL"。
    #
    # 不加空分组集 ()：SQLAlchemy 会把裸 () 当作绑定参数而非 SQL 的空分组集。
    # 总数直接由 by_type 的各组计数求和得到——exception_type 非空，每行必属于
    # 且仅属于一个 exception_type 分组，求和即窗口内总行数。
    stmt = (
        select(
            ExceptionLog.exception_type,
            ExceptionLog.error_code,
            ExceptionLog.status_code,
            ExceptionLog.user_id,
            # 标签不能叫 count：Row 是 tuple 子类，自带 count/index 成员，
            # 同名标签会被遮蔽，row.count 取到的是那个成员而非列值。
            func.count(ExceptionLog.id).label("hit_count"),
            func.grouping(ExceptionLog.exception_type).label("g_type"),
            func.grouping(ExceptionLog.error_code).label("g_error_code"),
            func.grouping(ExceptionLog.status_code).label("g_status_code"),
            func.grouping(ExceptionLog.user_id).label("g_user"),
        )
        .where(ExceptionLog.created_at >= cutoff_time)
        .group_by(
            func.grouping_sets(
                ExceptionLog.exception_type,
                ExceptionLog.error_code,
                ExceptionLog.status_code,
                ExceptionLog.user_id,
            )
        )
    )

    by_type: List[Tuple[Any, int]] = []
    by_error_code: List[Tuple[Any, int]] = []
    by_status_code: List[Tuple[Any, int]] = []
    by_user: List[Tuple[Any, int]] = []

    for row in (await db.execute(stmt)).all():
        count = int(row.hit_count or 0)
        if not row.g_type:
            by_type.append((row.exception_type, count))
        elif not row.g_error_code:
            by_error_code.append((row.error_code, count))
        elif not row.g_status_code:
            by_status_code.append((row.status_code, count))
        elif not row.g_user:
            by_user.append((row.user_id, count))

    # top-N 截断之前求和，否则总数会被截断影响
    total = sum(count for _, count in by_type)

    return {
        "time_window_hours": time_window_hours,
        "total_exceptions": total,
        "by_exception_type": _top(by_type),
        "by_error_code": _top(by_error_code),
        "by_status_code": _top(by_status_code, limit=None),
        "by_user": _top(by_user),
    }
