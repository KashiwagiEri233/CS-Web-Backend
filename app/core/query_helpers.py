"""SQL 查询构造 helper（重复实现治理波次 B2b 收敛 FTS / JSONB contains 同源写法）。"""

from sqlalchemy import func, text, type_coerce
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import settings


def fts_condition(model, keyword: str):
    """全文检索条件：`search_vector @@ websearch_to_tsquery`（GIN 索引加速）。

    收敛 community 路由 / community_repo / search_service 三处同源构造。
    """
    ts_query = func.websearch_to_tsquery(
        text(f"'{settings.FTS_CONFIG}'"), keyword.strip()
    )
    return model.search_vector.op("@@")(ts_query)


def jsonb_contains(column, value):
    """JSONB `@>` 包含判断。

    ``ColumnElement.contains`` 对 JSON 变体会退化成字符串 LIKE（运行时
    invalid input syntax for type json）；``type_coerce(..., JSONB).contains(...)``
    走 JSONB ``@>``。收敛 community / event / tools / community_repo 五处同源写法。
    """
    return type_coerce(column, JSONB).contains(value)
