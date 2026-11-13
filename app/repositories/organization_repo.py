"""组织数据访问层：峰、成员档案与作用范围查询。"""

from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import MemberProfile, Peak
from app.models.task import TaskClaim, TaskClaimMember
from app.models.user import User, user_roles
from app.models.role import Role
from app.models.wallet import WalletAccount
from app.repositories.base import paginate


class OrganizationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ 峰

    async def get_peak_by_id(self, peak_id: int) -> Optional[Peak]:
        result = await self.db.execute(select(Peak).where(Peak.id == peak_id))
        return result.scalar_one_or_none()

    async def get_peak_by_code(self, code: str) -> Optional[Peak]:
        result = await self.db.execute(select(Peak).where(Peak.code == code))
        return result.scalar_one_or_none()

    async def list_peaks(
        self, *, active_only: bool = True, skip: int = 0, limit: int = 100
    ) -> List[Peak]:
        stmt = select(Peak).order_by(Peak.id)
        if active_only:
            stmt = stmt.where(Peak.is_active.is_(True), Peak.archived_at.is_(None))
        result = await self.db.execute(paginate(stmt, skip, limit))
        return list(result.scalars().all())

    async def count_peaks(self, *, active_only: bool = True) -> int:
        stmt = select(func.count()).select_from(Peak)
        if active_only:
            stmt = stmt.where(Peak.is_active.is_(True), Peak.archived_at.is_(None))
        return int((await self.db.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------ 成员

    async def get_member_by_user_id(self, user_id: int) -> Optional[MemberProfile]:
        result = await self.db.execute(
            select(MemberProfile).where(MemberProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_member_row(self, member_id: int) -> Optional[dict]:
        result = await self.db.execute(
            select(MemberProfile, User, Peak)
            .join(User, User.id == MemberProfile.user_id)
            .outerjoin(Peak, Peak.id == MemberProfile.peak_id)
            .where(MemberProfile.id == member_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return self._member_dict(*row)

    async def list_member_rows(
        self,
        *,
        peak_ids: Optional[Sequence[int]] = None,
        keyword: Optional[str] = None,
        membership_status: Optional[str] = None,
        peak_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[dict]:
        stmt = (
            select(MemberProfile, User, Peak)
            .join(User, User.id == MemberProfile.user_id)
            .outerjoin(Peak, Peak.id == MemberProfile.peak_id)
            .order_by(MemberProfile.id)
        )
        if peak_ids is not None:
            stmt = stmt.where(MemberProfile.peak_id.in_(list(peak_ids)))
        if peak_id is not None:
            stmt = stmt.where(MemberProfile.peak_id == peak_id)
        if membership_status:
            stmt = stmt.where(MemberProfile.membership_status == membership_status)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(
                (User.username.ilike(pattern))
                | (User.display_name.ilike(pattern))
                | (MemberProfile.student_id.ilike(pattern))
            )
        result = await self.db.execute(paginate(stmt, skip, limit))
        return [self._member_dict(*row) for row in result.all()]

    async def count_members(
        self,
        *,
        peak_ids: Optional[Sequence[int]] = None,
        keyword: Optional[str] = None,
        membership_status: Optional[str] = None,
        peak_id: Optional[int] = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(MemberProfile)
            .join(User, User.id == MemberProfile.user_id)
        )
        if peak_ids is not None:
            stmt = stmt.where(MemberProfile.peak_id.in_(list(peak_ids)))
        if peak_id is not None:
            stmt = stmt.where(MemberProfile.peak_id == peak_id)
        if membership_status:
            stmt = stmt.where(MemberProfile.membership_status == membership_status)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(
                (User.username.ilike(pattern))
                | (User.display_name.ilike(pattern))
                | (MemberProfile.student_id.ilike(pattern))
            )
        return int((await self.db.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------ 作用范围与离会检查

    async def get_role_scopes(self, user_id: int) -> List[dict]:
        """读取用户的角色作用范围（用于组织数据范围过滤）。"""
        result = await self.db.execute(
            select(Role.name, user_roles.c.scope_type, user_roles.c.scope_peak_id)
            .select_from(user_roles)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(user_roles.c.user_id == user_id, Role.is_active.is_(True))
        )
        return [
            {"role_name": name, "scope_type": scope, "scope_peak_id": peak_id}
            for name, scope, peak_id in result.all()
        ]

    async def user_wallet_balance(self, user_id: int) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.sum(WalletAccount.balance), 0)).where(
                WalletAccount.kind == "user",
                WalletAccount.owner_user_id == user_id,
            )
        )
        return int(result.scalar_one())

    async def active_claim_count(self, user_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(TaskClaim)
            .join(TaskClaimMember, TaskClaimMember.claim_id == TaskClaim.id)
            .where(
                TaskClaimMember.user_id == user_id,
                TaskClaim.status.in_(["active", "submitted"]),
            )
        )
        return int(result.scalar_one())

    @staticmethod
    def _member_dict(profile: MemberProfile, user: User, peak: Optional[Peak]) -> dict:
        return {
            "id": profile.id,
            "user_id": profile.user_id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "student_id": profile.student_id,
            "peak_id": profile.peak_id,
            "peak_name": (peak.fantasy_name or peak.name) if peak else None,
            "membership_status": profile.membership_status,
            "joined_at": profile.joined_at,
            "left_at": profile.left_at,
            "version": profile.version,
        }
