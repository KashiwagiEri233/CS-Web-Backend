"""社区评论仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.community import CommunityComment
from app.repositories.base import paginate


class CommunityCommentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_post(
        self, post_id: int, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityComment], int]:
        conditions = [
            CommunityComment.post_id == post_id,
            CommunityComment.status == "published",
            CommunityComment.parent_comment_id.is_(None),
        ]
        total = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityComment)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(CommunityComment)
            .where(*conditions)
            .order_by(CommunityComment.created_at.asc()),
            skip,
            limit,
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def list_nested(self, parent_comment_id: int) -> list[CommunityComment]:
        stmt = (
            select(CommunityComment)
            .where(
                CommunityComment.parent_comment_id == parent_comment_id,
                CommunityComment.status == "published",
            )
            .order_by(CommunityComment.created_at.asc())
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def list_for_author(
        self, author_id: int, *, skip: int, limit: int
    ) -> tuple[list[CommunityComment], int]:
        conditions = [
            CommunityComment.author_id == author_id,
            CommunityComment.status == "published",
        ]
        total = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityComment)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(CommunityComment)
            .where(*conditions)
            .order_by(CommunityComment.created_at.desc()),
            skip,
            limit,
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, comment_id: int) -> Optional[CommunityComment]:
        return await self.db.get(CommunityComment, comment_id)

    async def create(self, data: dict) -> CommunityComment:
        obj = CommunityComment(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, comment: CommunityComment, content: str) -> None:
        comment.content_markdown = content
        comment.updated_at = now_utc()

    async def set_status(self, comment_id: int, status: str) -> None:
        comment = await self.get_by_id(comment_id)
        if comment is None:
            return
        comment.status = status
        comment.updated_at = now_utc()