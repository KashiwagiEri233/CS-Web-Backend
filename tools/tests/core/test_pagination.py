"""分页基类单元测试：PaginatedResponse 序列化。不依赖数据库。

注：PaginationParams 的默认值是 FastAPI ``Query(...)``，仅在依赖注入时解析为 0/100，
直接实例化拿到的是 FieldInfo——故其默认/边界行为由路由 e2e（test_users.py）通过真实 DI 验证。
"""

from pydantic import BaseModel

from app.schemas.pagination import PaginatedResponse


class _Item(BaseModel):
    id: int
    name: str


def test_paginated_response_shape():
    resp = PaginatedResponse[_Item](
        items=[_Item(id=1, name="a"), _Item(id=2, name="b")],
        total=2,
        skip=0,
        limit=100,
    )
    data = resp.model_dump(mode="json")
    assert set(data.keys()) == {"items", "total", "skip", "limit", "total_pages"}
    assert data["total"] == 2
    assert data["total_pages"] == 1
    assert len(data["items"]) == 2
    assert data["items"][0] == {"id": 1, "name": "a"}


def test_paginated_response_empty():
    resp = PaginatedResponse[_Item](items=[], total=0, skip=0, limit=100)
    dumped = resp.model_dump()
    assert dumped["items"] == []
    assert dumped["total_pages"] == 1  # 至少 1 页


def test_paginated_response_total_pages_multi():
    """total=21, limit=20 → total_pages=2"""
    resp = PaginatedResponse[_Item](
        items=[_Item(id=1, name="a")],
        total=21,
        skip=0,
        limit=20,
    )
    assert resp.total_pages == 2
