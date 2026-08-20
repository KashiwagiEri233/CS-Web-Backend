"""贡献热力图数据服务：GitHub 公开抓取 + 缓存（6h 惰性刷新）。

- GitHub：无 token 抓取 https://github.com/users/{username}/contributions 页面，
  解析 ContributionCalendar 的 data-date / data-count 数据（非官方但长期稳定）。
- 缓存：按 user_id + platform + year 存库；6 小时内过期则重抓，抓取失败回退旧缓存。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CONTRIBUTION_CACHE_TTL_SECONDS
from app.core.timezone import now_utc, iso_or_none
from app.models.contribution import ContributionCache

_GITHUB_CONTRIBUTIONS_URL = "https://github.com/users/{username}/contributions"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# <td ... data-date="2026-08-01" data-level="3" ...>...</td>，块内含 tooltip "11 contributions"
_TD_RE = re.compile(
    r'<td[^>]*data-date="(\d{4}-\d{2}-\d{2})"[^>]*data-level="\d"[^>]*>(.*?)</td>',
    re.S,
)
_TOOLTIP_RE = re.compile(r"(\d+)\s+contributions", re.I)
# 旧版 rect 格式：<rect ... data-date="2026-01-01" data-count="3" ...>
_RECT_RE = re.compile(r'data-date="(\d{4}-\d{2}-\d{2})"[^>]*data-count="(\d+)"')


def _parse_contributions(html: str) -> dict[str, int]:
    """解析贡献页 HTML → {date: count}。兼容新 td 格式与旧 rect 格式。"""
    result: dict[str, int] = {}

    # 优先 rect data-count（含真实次数）
    for date, count in _RECT_RE.findall(html):
        result[date] = max(result.get(date, 0), int(count))

    # td + tooltip（新版）："N contributions"
    for date, inner in _TD_RE.findall(html):
        match = _TOOLTIP_RE.search(inner)
        if match:
            count = int(match.group(1))
            result[date] = max(result.get(date, 0), count)
        else:
            result.setdefault(date, 0)

    return result


def _calc_streak(daily: dict[str, int], today: datetime) -> int:
    """当前连续贡献天数（从今天往回数，今天未贡献不断链直到昨天）。"""
    day = today.date()
    # 今天无贡献时从昨天开始数（GitHub 惯例：今天还没贡献不算断）
    if daily.get(day.isoformat(), 0) == 0:
        day -= timedelta(days=1)
    streak = 0
    while daily.get(day.isoformat(), 0) > 0:
        streak += 1
        day -= timedelta(days=1)
    return streak


class ContributionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_github(
        self,
        user_id: int,
        username: str,
        year: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """获取 GitHub 贡献热力图。返回 {platform, username, year, data, total, streak, fetched_at, stale}。"""
        now = now_utc()
        target_year = year or now.year
        username = username.strip().lstrip("@")

        cache = (
            await self.db.execute(
                select(ContributionCache).where(
                    ContributionCache.user_id == user_id,
                    ContributionCache.platform == "github",
                    ContributionCache.year == target_year,
                )
            )
        ).scalar_one_or_none()

        stale = False
        fresh_enough = (
            cache is not None
            and (now - cache.fetched_at).total_seconds()
            < CONTRIBUTION_CACHE_TTL_SECONDS
        )

        if fresh_enough and not force_refresh:
            return self._to_payload(cache, stale=False)

        # 需要抓取
        try:
            daily, total = await self._fetch_github(username, target_year)
            streak = _calc_streak(daily, now)
            data = [
                {"date": date, "count": count}
                for date, count in sorted(daily.items())
                if date.startswith(f"{target_year}-")
            ]
            payload = {
                "platform": "github",
                "username": username,
                "year": target_year,
                "data": data,
                "total": total,
                "streak": streak,
            }
            if cache is None:
                cache = ContributionCache(
                    user_id=user_id,
                    platform="github",
                    username=username,
                    year=target_year,
                )
                self.db.add(cache)
            cache.username = username
            cache.data = data
            cache.total = total
            cache.streak = streak
            cache.fetched_at = now
            await self.db.commit()
            return {**payload, "fetched_at": now.isoformat(), "stale": False}
        except Exception as exc:  # noqa: BLE001 - 抓取失败降级为旧缓存
            logger.warning(
                "github contributions fetch failed",
                username=username,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if cache is not None:
                return self._to_payload(cache, stale=True)
            # 无缓存且抓取失败：返回结构化「不可达」标记（前端据此展示友好错误态），不再抛 500
            return {
                "platform": "github",
                "username": username,
                "year": target_year,
                "data": [],
                "total": 0,
                "streak": 0,
                "fetched_at": None,
                "stale": False,
                "unreachable": True,
            }

    async def _fetch_github(
        self, username: str, year: int
    ) -> tuple[dict[str, int], int]:
        url = _GITHUB_CONTRIBUTIONS_URL.format(username=username)
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": _UA, "Accept": "text/html"},
            )
            resp.raise_for_status()

        daily = _parse_contributions(resp.text)
        if not daily:
            raise RuntimeError(
                "no contribution data parsed (username invalid or page structure changed)"
            )

        # 本年数据（页面本身是全年滚动窗口，按目标年份过滤）
        year_daily = {d: c for d, c in daily.items() if d.startswith(f"{year}-")}
        total = sum(year_daily.values())
        return year_daily, total

    @staticmethod
    def _to_payload(cache: ContributionCache, stale: bool) -> dict:
        return {
            "platform": cache.platform,
            "username": cache.username,
            "year": cache.year,
            "data": cache.data or [],
            "total": cache.total,
            "streak": cache.streak,
            "fetched_at": iso_or_none(cache.fetched_at),
            "stale": stale,
        }
