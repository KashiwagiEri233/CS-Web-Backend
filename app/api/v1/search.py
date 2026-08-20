"""全站搜索 API：GET /api/v1/search?q=&scope=&limit=。

- q：必填，1~80 字符。
- scope：all（默认）| events | community | tools | announcements | users。
- limit：每类返回条数，默认 5，上限 10。
- 响应：{ query, scope, results: { <scope>: { items: [...], total } } }。

设计：只读公开端点，聚合各模块既有搜索能力（见 services/search_service.py）。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.dependencies_services import get_search_service
from app.services.search_service import SCOPES, SearchService

router = APIRouter()


class SearchResultItem(BaseModel):
    """统一搜索结果项：type / id / title / subtitle / url。"""

    type: str
    id: int
    title: str
    subtitle: str = ""
    url: str = ""


class SearchGroup(BaseModel):
    """单个范围的搜索结果组。"""

    items: list[SearchResultItem] = []
    total: int = 0


class SearchResponse(BaseModel):
    """全站搜索聚合响应。"""

    query: str
    scope: str
    results: dict[str, SearchGroup]


@router.get("", response_model=SearchResponse, tags=["搜索"])
async def global_search(
    q: str = Query(..., min_length=1, max_length=80, description="搜索关键词"),
    scope: str = Query("all", description="搜索范围"),
    limit: int = Query(5, ge=1, le=10, description="每类返回条数"),
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    """全站聚合搜索：hero 页传 scope=all；模块页传对应单 scope。"""
    if scope not in ("all", *SCOPES):
        scope = "all"
    results = await service.search(q=q, scope=scope, limit=limit)
    return SearchResponse(
        query=q.strip(),
        scope=scope,
        results={name: SearchGroup(**group) for name, group in results.items()},
    )
