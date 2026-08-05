"""测试 app/core/timezone.py 的时区工具函数。

覆盖：
- now_utc() 返回 UTC aware datetime
- now_local() 返回配置时区 aware datetime
- utc_to_local() 正确转换 / None 透传 / naive 容错
- local_to_utc() 正确转换 / None 透传 / naive 容错
"""

from datetime import datetime, timezone

from app.core.timezone import now_utc, now_local, utc_to_local, local_to_utc


class TestNowUtc:
    def test_returns_aware_datetime(self):
        dt = now_utc()
        assert dt.tzinfo is not None
        assert dt.tzinfo == timezone.utc

    def test_is_monotonic(self):
        d1 = now_utc()
        d2 = now_utc()
        assert d2 >= d1


class TestNowLocal:
    def test_returns_aware_datetime(self):
        dt = now_local()
        assert dt.tzinfo is not None

    def test_matches_config_timezone(self):
        from app.core.config import settings

        dt = now_local()
        assert dt.tzinfo == settings.tzinfo


class TestUtcToLocal:
    def test_converts_utc_to_local(self):
        from app.core.config import settings

        utc_dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        local_dt = utc_to_local(utc_dt)
        assert local_dt is not None
        assert local_dt.tzinfo == settings.tzinfo
        # 同一时刻，UTC 与本地时间差应为时区偏移
        assert local_dt.astimezone(timezone.utc) == utc_dt

    def test_none_passes_through(self):
        assert utc_to_local(None) is None

    def test_naive_treated_as_utc(self):
        from app.core.config import settings

        naive = datetime(2024, 6, 1, 12, 0, 0)
        local_dt = utc_to_local(naive)
        assert local_dt is not None
        assert local_dt.tzinfo == settings.tzinfo


class TestLocalToUtc:
    def test_converts_local_to_utc(self):
        from app.core.config import settings

        local_dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=settings.tzinfo)
        utc_dt = local_to_utc(local_dt)
        assert utc_dt is not None
        assert utc_dt.tzinfo == timezone.utc

    def test_none_passes_through(self):
        assert local_to_utc(None) is None

    def test_naive_treated_as_local(self):
        from app.core.config import settings

        naive = datetime(2024, 6, 1, 12, 0, 0)
        utc_dt = local_to_utc(naive)
        assert utc_dt is not None
        assert utc_dt.tzinfo == timezone.utc
        # 原始 naive 被附加了本地时区，再转 UTC，偏移量应一致
        assert utc_dt.astimezone(settings.tzinfo).replace(tzinfo=None) == naive
