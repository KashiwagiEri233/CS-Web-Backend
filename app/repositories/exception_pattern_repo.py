"""
异常模式仓储层
提供异常模式的数据库操作方法
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exception_log import ExceptionPattern


class ExceptionPatternRepository:
    """异常模式仓储"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_pattern(self, pattern_data: Dict[str, Any]) -> ExceptionPattern:
        """
        创建异常模式

        Args:
            pattern_data: 模式数据

        Returns:
            创建的模式对象
        """
        pattern = ExceptionPattern(**pattern_data)
        self.db.add(pattern)
        await self.db.commit()
        await self.db.refresh(pattern)
        return pattern

    async def get_pattern_by_id(self, pattern_id: int) -> Optional[ExceptionPattern]:
        """
        通过ID获取异常模式

        Args:
            pattern_id: 模式ID

        Returns:
            模式对象或None
        """
        result = await self.db.execute(
            select(ExceptionPattern).where(ExceptionPattern.id == pattern_id)
        )
        return result.scalar_one_or_none()

    async def get_pattern_by_name(
        self, pattern_name: str
    ) -> Optional[ExceptionPattern]:
        """
        通过名称获取异常模式

        Args:
            pattern_name: 模式名称

        Returns:
            模式对象或None
        """
        result = await self.db.execute(
            select(ExceptionPattern).where(
                ExceptionPattern.pattern_name == pattern_name
            )
        )
        return result.scalar_one_or_none()

    async def get_active_patterns(self) -> List[ExceptionPattern]:
        """
        获取所有活跃的异常模式

        Returns:
            活跃模式列表
        """
        result = await self.db.execute(
            select(ExceptionPattern).where(ExceptionPattern.is_active == True)
        )
        return list(result.scalars().all())

    async def update_pattern(
        self, pattern_id: int, update_data: Dict[str, Any]
    ) -> Optional[ExceptionPattern]:
        """
        更新异常模式

        Args:
            pattern_id: 模式ID
            update_data: 更新数据

        Returns:
            更新后的模式对象或None
        """
        result = await self.db.execute(
            select(ExceptionPattern).where(ExceptionPattern.id == pattern_id)
        )
        pattern = result.scalar_one_or_none()

        if not pattern:
            return None

        for field, value in update_data.items():
            if hasattr(pattern, field):
                setattr(pattern, field, value)

        await self.db.commit()
        await self.db.refresh(pattern)
        return pattern

    async def increment_pattern_occurrence(
        self, pattern_id: int
    ) -> Optional[ExceptionPattern]:
        """
        增加模式出现次数

        Args:
            pattern_id: 模式ID

        Returns:
            更新后的模式对象或None
        """
        result = await self.db.execute(
            select(ExceptionPattern).where(ExceptionPattern.id == pattern_id)
        )
        pattern = result.scalar_one_or_none()

        if not pattern:
            return None

        pattern.occurrence_count += 1
        pattern.last_occurrence = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(pattern)
        return pattern
