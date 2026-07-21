"""仓储层基类：抽取通用 CRUD，消除各 repo 的重复样板（DRY）。

子类只需声明 ``model`` 类属性即可获得 get_by_id / create / update；
特化查询（如按用户名、预加载关联）在子类自行追加。

事务约定（全项目统一）：
- Repository **只 flush**，不 commit。
- 由 **Service**（或路由外的编排代码）显式 ``await db.commit()``。
- 这样跨多个 repo 的业务可以在同一事务内完成，避免半提交。
"""

from typing import Any, Generic, Optional, Protocol, Type, TypeVar, cast

from sqlalchemy import select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession


class _HasId(Protocol):
    """所有 ORM 实体都满足的最小仓储协议。"""

    id: Any


# 不用 bound=Base：运行时 import database 会经 lifecycle → rbac_init → repo 形成环。
ModelT = TypeVar("ModelT", bound=_HasId)


def dml_rowcount(result: Any) -> int:
    """取 DML（insert/update/delete）语句的受影响行数。

    类型层面 ``Result`` 不保证有 ``rowcount``（SELECT 结果没有），但 DML 语句
    实际返回 ``CursorResult``，此处集中做一次 cast，避免各 repo 重复忽略类型错误。
    """
    return int(cast(CursorResult, result).rowcount or 0)


class BaseRepository(Generic[ModelT]):
    """通用异步仓储基类。子类须设置类属性 ``model``。"""

    model: Type[ModelT]

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id_) -> Optional[ModelT]:
        stmt = select(self.model).where(self.model.id == id_)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> ModelT:
        """新增并 flush（未 commit）；调用方负责 commit。"""
        obj = self.model(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: ModelT) -> ModelT:
        """更新并 flush（未 commit）；调用方负责 commit。"""
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj
