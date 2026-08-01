"""积分服务：余额 / 流水 / 排行榜 / 等级。"""

from __future__ import annotations

from typing import Optional, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException, ErrorCode
from app.models.user import User
from app.repositories.tools_repo import PointsRepository


class _LevelThreshold(TypedDict):
    level: int
    title: str
    min_points: int


# 等级阈值（与前端 LEVEL_THRESHOLDS 对齐）
LEVEL_THRESHOLDS: list[_LevelThreshold] = [
    {"level": 1, "title": "新手学徒", "min_points": 0},
    {"level": 2, "title": "初级成员", "min_points": 50},
    {"level": 3, "title": "活跃成员", "min_points": 150},
    {"level": 4, "title": "骨干成员", "min_points": 400},
    {"level": 5, "title": "核心骨干", "min_points": 1000},
    {"level": 6, "title": "技术专家", "min_points": 2500},
    {"level": 7, "title": "协会元老", "min_points": 5000},
]


def calculate_level(points: int) -> dict:
    result = LEVEL_THRESHOLDS[0]
    for threshold in LEVEL_THRESHOLDS:
        if points >= threshold["min_points"]:
            result = threshold
    return {"level": result["level"], "title": result["title"]}


class PointsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PointsRepository(db)

    async def balance(self, user_id: int) -> int:
        return await self.repo.last_balance(user_id)

    async def add_points(
        self,
        user_id: int,
        amount: int,
        source_type: str,
        source_id: Optional[int],
        reason: str,
    ) -> dict:
        if amount <= 0:
            raise ValidationException(
                message="积分数量必须大于 0",
                error_code=ErrorCode.Validation.VALIDATION_FAILED,
            )
        balance = await self.balance(user_id)
        tx = await self.repo.create_transaction(
            user_id=user_id,
            amount=amount,
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            balance_after=balance + amount,
        )
        await self.db.commit()
        return self._to_out(tx)

    async def deduct_points(
        self,
        user_id: int,
        amount: int,
        source_type: str,
        source_id: Optional[int],
        reason: str,
    ) -> dict:
        if amount <= 0:
            raise ValidationException(
                message="扣除数量必须大于 0",
                error_code=ErrorCode.Validation.VALIDATION_FAILED,
            )
        balance = await self.balance(user_id)
        if balance < amount:
            raise ValidationException(
                message=f"积分不足（当前 {balance}，需要 {amount}）",
                error_code=ErrorCode.Validation.VALIDATION_FAILED,
            )
        tx = await self.repo.create_transaction(
            user_id=user_id,
            amount=-amount,
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            balance_after=balance - amount,
        )
        await self.db.commit()
        return self._to_out(tx)

    async def profile(self, user_id: int) -> dict:
        balance = await self.balance(user_id)
        level = calculate_level(balance)
        txs = await self.repo.list_transactions(user_id)
        return {
            "balance": balance,
            "level": level["level"],
            "level_title": level["title"],
            "transactions": [self._to_out(t) for t in txs],
        }

    async def leaderboard(self, top_n: int = 20) -> list[dict]:
        rows = await self.repo.leaderboard(top_n)
        users = {}
        if rows:
            users = {
                u.id: u
                for u in (
                    await self.db.execute(
                        select(User).where(User.id.in_([uid for uid, _ in rows]))
                    )
                )
                .scalars()
                .all()
            }
        result = []
        for user_id, balance in rows:
            level = calculate_level(balance)
            user = users.get(user_id)
            result.append(
                {
                    "user_id": user_id,
                    "display_name": (
                        (user.display_name or user.username) if user else None
                    ),
                    "balance": balance,
                    "level": level["level"],
                    "level_title": level["title"],
                }
            )
        return result

    def _to_out(self, tx) -> dict:
        return {
            "id": tx.id,
            "user_id": tx.user_id,
            "amount": tx.amount,
            "reason": tx.reason,
            "source_type": tx.source_type,
            "source_id": tx.source_id,
            "balance_after": tx.balance_after,
            "created_at": tx.created_at,
        }
