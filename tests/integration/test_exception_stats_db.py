"""异常统计聚合的数据库集成测试（需要 PostgreSQL）。

fetch_exception_statistics 用 ``GROUP BY GROUPING SETS`` 把原来的 5 条查询压成一次
表扫描。这类 SQL 无法用 mock 验证——分组标志位的判读、NULL 键的剔除、总数的推导
全都依赖真实数据库语义，所以必须实跑。
"""

import uuid

from sqlalchemy import text

from app.core.timezone import now_utc
from app.database import get_session
from app.models.exception_log import ExceptionLog
from app.repositories.exception_log_stats import fetch_exception_statistics


async def test_grouping_sets_statistics_match_expected(integration_db_ready):
    marker = uuid.uuid4().hex[:8]
    # (exception_type, error_code, status_code, user_id)
    rows = [
        (f"ValueError_{marker}", f"E1_{marker}", 500, f"u1_{marker}"),
        (f"ValueError_{marker}", f"E1_{marker}", 500, f"u1_{marker}"),
        (f"KeyError_{marker}", f"E2_{marker}", 400, f"u2_{marker}"),
        (f"KeyError_{marker}", None, 400, f"u2_{marker}"),  # error_code 为空
        (f"TypeError_{marker}", f"E2_{marker}", 500, None),  # user_id 为空
    ]

    async with get_session() as db:
        # 本用例断言全表聚合，先清空避免其它用例残留数据干扰
        await db.execute(text("TRUNCATE exception_logs RESTART IDENTITY CASCADE"))
        for index, (exc_type, error_code, status_code, user_id) in enumerate(rows):
            db.add(
                ExceptionLog(
                    traceback_id=f"tb_{marker}_{index}",
                    exception_type=exc_type,
                    error_code=error_code,
                    exception_message="integration",
                    status_code=status_code,
                    user_id=user_id,
                    details={"k": "v"},
                    created_at=now_utc(),
                )
            )
        await db.commit()

        try:
            stats = await fetch_exception_statistics(db, time_window_hours=24)

            # 总数由各分组计数求和推导（不再单独查一次 COUNT）
            assert stats["total_exceptions"] == 5
            assert stats["by_exception_type"] == {
                f"ValueError_{marker}": 2,
                f"KeyError_{marker}": 2,
                f"TypeError_{marker}": 1,
            }
            # NULL 键必须被剔除：error_code 缺失的那条不计入任何 error_code 分组
            assert stats["by_error_code"] == {f"E1_{marker}": 2, f"E2_{marker}": 2}
            assert stats["by_status_code"] == {500: 3, 400: 2}
            assert stats["by_user"] == {f"u1_{marker}": 2, f"u2_{marker}": 2}
        finally:
            await db.execute(text("TRUNCATE exception_logs RESTART IDENTITY CASCADE"))
            await db.commit()


async def test_jsonb_roundtrips_as_dict(integration_db_ready):
    """JSON 列已迁移为 jsonb：写入 dict，读回仍是 dict 而非字符串。"""
    marker = uuid.uuid4().hex[:8]
    payload = {"nested": {"n": 1}, "list": [1, 2, 3]}

    async with get_session() as db:
        row = ExceptionLog(
            traceback_id=f"tb_json_{marker}",
            exception_type="JsonProbe",
            exception_message="integration",
            details=payload,
            context={"ctx": True},
            created_at=now_utc(),
        )
        db.add(row)
        await db.commit()
        row_id = row.id

        try:
            fetched = await db.get(ExceptionLog, row_id)
            assert isinstance(fetched.details, dict)
            assert fetched.details == payload
            assert fetched.context == {"ctx": True}
        finally:
            await db.execute(
                text("DELETE FROM exception_logs WHERE id = :i"), {"i": row_id}
            )
            await db.commit()
