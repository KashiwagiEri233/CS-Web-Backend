"""仓储层基类：抽取通用 CRUD，消除各 repo 的重复样板（DRY）。

子类只需声明 ``model`` 类属性即可获得 get_by_id / get_all / count / create / update / delete；
特化查询（如按用户名、预加载关联）在子类自行追加。

约定（与路由层一致）：create/update/delete 内部 commit；查询方法不提交。
"""

from typing import Generic, List, Optional, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """通用异步仓储基类。子类须设置类属性 ``model``。"""

    model: Type[ModelT]

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id_) -> Optional[ModelT]:
        stmt = select(self.model).where(self.model.id == id_)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[ModelT]:
        stmt = select(self.model).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """统计总行数（用于分页 total）。"""
        stmt = select(func.count()).select_from(self.model)
        result = await self.db.execute(stmt)
        return int(result.scalar_one())

    async def create(self, data: dict) -> ModelT:
        obj = self.model(**data)
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: ModelT) -> ModelT:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def delete(self, id_) -> bool:
        obj = await self.get_by_id(id_)
        if obj is None:
            return False
        await self.db.delete(obj)
        await self.db.commit()
        return True
