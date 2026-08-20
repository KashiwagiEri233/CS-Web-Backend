"""统一分页参数与响应模型。

列表接口约定：查询参数走 ``PaginationParams``（?skip=&limit= 或 ?page=&page_size=），
响应走 ``PaginatedResponse[T]``（含 items + total + skip + limit + total_pages），
便于前端拿到总数做分页器，且各列表接口结构一致。
"""

import math
from typing import Generic, List, Optional, TypeVar

from fastapi import Query
from pydantic import BaseModel, model_validator

T = TypeVar("T")


def compute_total_pages(total: int, size: int) -> int:
    """统一 total_pages 算法（全项目分页响应共用）。

    规则：``ceil(total / size)`` 且**至少 1**（0 数据也视为 1 页），与
    ``PaginatedResponse`` 内部规则一致；``size <= 0``（如 admin_events 整表单页空表时
    size=0）回退 1，避免除零。调用方不再手算，消除边界算法漂移。
    """
    if size <= 0:
        return 1
    return max(1, math.ceil(total / size))


class PaginationParams:
    """分页查询参数依赖。用法：``pagination: PaginationParams = Depends()``。

    同时支持两种分页风格：
    - **offset 风格**：``?skip=0&limit=100``（原始约定，向后兼容）
    - **page 风格**：``?page=1&page_size=20``（前端 BFF 常用）

    当 ``page`` 提供时，自动计算 ``skip = (page - 1) * page_size``；
    ``page_size`` 未提供时回退到 ``limit``。
    """

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="跳过的记录数（与 page 互斥）"),
        limit: int = Query(100, ge=1, le=500, description="每页返回的最大记录数"),
        page: Optional[int] = Query(
            None,
            ge=1,
            description="页码（1-based，提供时与 page_size 一起计算 skip/limit）",
        ),
        page_size: Optional[int] = Query(
            None, ge=1, le=500, description="每页大小（提供时覆盖 limit）"
        ),
    ):
        if page is not None:
            ps = page_size or limit
            self.skip = (page - 1) * ps
            self.limit = ps
        else:
            self.skip = skip
            self.limit = limit


class PaginatedResponse(BaseModel, Generic[T]):
    """统一分页响应包装。

    ``total_pages`` 由 ``total`` 和 ``limit`` 自动计算（``ceil(total/limit)``，至少 1），
    无需调用方手动传入。
    """

    items: List[T]
    total: int
    skip: int
    limit: int
    total_pages: int = 0

    @model_validator(mode="after")
    def _compute_total_pages(self) -> "PaginatedResponse[T]":
        self.total_pages = compute_total_pages(self.total, self.limit)
        return self
