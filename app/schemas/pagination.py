"""统一分页参数与响应模型。

列表接口约定：查询参数走 ``PaginationParams``（?skip=&limit=），
响应走 ``PaginatedResponse[T]``（含 items + total + skip + limit），
便于前端拿到总数做分页器，且各列表接口结构一致。
"""

from typing import Generic, List, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams:
    """分页查询参数依赖。用法：``pagination: PaginationParams = Depends()``。"""

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="跳过的记录数"),
        limit: int = Query(100, ge=1, le=500, description="每页返回的最大记录数"),
    ):
        self.skip = skip
        self.limit = limit


class PaginatedResponse(BaseModel, Generic[T]):
    """统一分页响应包装。"""

    items: List[T]
    total: int
    skip: int
    limit: int
