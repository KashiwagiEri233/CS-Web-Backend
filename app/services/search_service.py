"""全站搜索服务：聚合 events / community / tools / announcements / users 五大范围的搜索结果。

设计约定（2026-08-20）：
- 本服务为纯新增、只读，不改动各模块既有 service 的签名。
- 复用各模块已有 search 能力（events / community posts 直接透传 search 参数，
  users 复用 search_vector 全文检索；resources 透传 `AuxilioToolRepository.search_resources`
  统一 SQL 实现——重复实现治理波次 A1）；announcements 数据量小，在服务内做 Python 端
  ilike 过滤，避免为聚合搜索改动既有模块查询。
- 统一输出扁平 SearchResultItem（type / id / title / subtitle / url），
  供前端顶栏下拉与 /search 结果页直接消费。
"""

from __future__ import annotations

import asyncio
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.community import CommunityPost
from app.models.user import User
from app.repositories.auxilio_tool_repo import AuxilioToolRepository
from app.services.announcement_service import AnnouncementService
from app.services.community.community_post import PostService
from app.services.event.event_service import EventService

# 支持的搜索范围（scope 参数合法值；scope=all 时全部启用）
SCOPES = ("events", "community", "tools", "announcements", "users")

_SUBTITLE_MAX = 120


def _truncate(value: Optional[str], max_len: int = _SUBTITLE_MAX) -> str:
    """截断长文本为摘要（保留原始内容，仅截断展示用 subtitle）。"""
    if not value:
        return ""
    value = value.replace("\n", " ").strip()
    return value if len(value) <= max_len else value[: max_len - 1] + "…"


class SearchService:
    """全站聚合搜索（只读）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------- 公开入口

    async def search(
        self,
        q: str,
        scope: str = "all",
        limit: int = 5,
    ) -> dict:
        """聚合搜索，返回 {scope: {"items": [...], "total": n}} 结构。"""
        q = q.strip()
        groups: dict = {}
        active = SCOPES if scope == "all" else (scope,)

        jobs = []
        for name in active:
            if name == "events":
                jobs.append((name, self._search_events(q, limit)))
            elif name == "community":
                jobs.append((name, self._search_community(q, limit)))
            elif name == "users":
                jobs.append((name, self._search_users(q, limit)))
            elif name == "announcements":
                jobs.append((name, self._search_announcements(q, limit)))
            elif name == "tools":
                jobs.append((name, self._search_resources(q, limit)))

        results = await asyncio.gather(*(job for _, job in jobs))
        for (name, _), group in zip(jobs, results):
            groups[name] = group
        return groups

    # ------------------------------------------------------------- 各范围

    async def _search_events(self, q: str, limit: int) -> dict:
        service = EventService(self.db)
        events, total = await service.list_events(search=q, limit=limit)
        items = [
            {
                "type": "event",
                "id": e.id,
                "title": e.title,
                "subtitle": _truncate(e.description),
                "url": "/events",
            }
            for e in events
        ]
        return {"items": items, "total": total}

    async def _search_community(self, q: str, limit: int) -> dict:
        service = PostService(self.db)
        posts, total = await service.list_posts(search=q, limit=limit)
        items = [
            {
                "type": "post",
                "id": p.id,
                "title": p.title,
                "subtitle": _truncate(p.excerpt or p.content_markdown),
                "url": f"/community/{p.id}",
            }
            for p in posts
        ]
        return {"items": items, "total": total}

    async def _search_users(self, q: str, limit: int) -> dict:
        """用户检索：复用 User.search_vector 全文检索（与 community/members 同源）。"""
        ts_query = func.websearch_to_tsquery(
            text(f"'{settings.FTS_CONFIG}'"), q
        )
        stmt = (
            select(User)
            .where(User.deleted_at.is_(None), User.search_vector.op("@@")(ts_query))
            .order_by(User.created_at.desc())
            .limit(limit)
        )
        users = (await self.db.scalars(stmt)).all()
        items = [
            {
                "type": "user",
                "id": u.id,
                "title": u.display_name or u.username,
                "subtitle": _truncate(u.bio),
                "url": f"/users/{u.id}",
            }
            for u in users
        ]
        return {"items": items, "total": len(users)}

    async def _search_announcements(self, q: str, limit: int) -> dict:
        """公告：生效列表数据量小，Python 端按 title/content 过滤。"""
        service = AnnouncementService(self.db)
        announcements = await service.list_active()
        ql = q.lower()
        matched = [
            a
            for a in announcements
            if ql in (a.title or "").lower() or ql in (a.content or "").lower()
        ]
        items = [
            {
                "type": "announcement",
                "id": a.id,
                "title": a.title,
                "subtitle": _truncate(a.content),
                "url": "",
            }
            for a in matched[:limit]
        ]
        return {"items": items, "total": len(matched)}

    async def _search_resources(self, q: str, limit: int) -> dict:
        """学习资源：透传统一 repo 搜索（标题/描述 ilike，已审核，浏览量倒序）。

        重复实现治理波次 A1：与学习助手 search_resources 工具共用同一 SQL 实现，
        保证同一关键词全站搜索与学习助手结果一致；不再受 100 条内存过滤上限。
        """
        rows = await AuxilioToolRepository(self.db).search_resources(q, limit=limit)
        items = [
            {
                "type": "resource",
                "id": r.id,
                "title": r.title,
                "subtitle": _truncate(r.description),
                "url": "/tools",
            }
            for r in rows
        ]
        return {"items": items, "total": len(items)}
