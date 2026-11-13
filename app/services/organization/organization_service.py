"""组织服务：峰与成员管理，含作用范围校验。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.timezone import now_utc
from app.models.organization import MemberProfile, Peak
from app.models.user import User
from app.models.wallet import WalletAccount
from app.repositories.organization_repo import OrganizationRepository
from app.repositories.rbac_repo import RBACRepository
from app.repositories.wallet_repo import WalletRepository
from app.services.rbac.rbac_service import RBACService


class OrganizationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = OrganizationRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.repo_wallet = WalletRepository(db)

    # ------------------------------------------------------------------ 作用范围

    async def _allowed_peak_ids(self, actor: User) -> Optional[set[int]]:
        """返回可管理峰集合；None 表示 all（超级用户或 all 范围绑定）。"""
        if actor.is_superuser:
            return None
        scopes = await self.repo.get_role_scopes(actor.id)
        if any(item["scope_type"] == "all" for item in scopes):
            return None
        peak_ids = {
            item["scope_peak_id"]
            for item in scopes
            if item["scope_type"] == "peak" and item["scope_peak_id"]
        }
        if not peak_ids:
            raise AuthorizationException(
                message="没有可管理的组织范围",
                error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
            )
        return peak_ids

    def _ensure_in_scope(self, peak_id: Optional[int], allowed: Optional[set[int]]) -> None:
        if allowed is None:
            return
        if peak_id is None or peak_id not in allowed:
            raise AuthorizationException(
                message="目标峰不在授权范围内",
                error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
                details={"peak_id": peak_id},
            )

    # ------------------------------------------------------------------ 本人

    async def get_me(self, user_id: int) -> dict:
        user = (
            await self.db.execute(
                select(User).where(User.id == user_id, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundException(
                message="用户不存在", resource_type="user", resource_id=user_id
            )
        profile = await self.repo.get_member_by_user_id(user_id)
        member = None
        if profile is not None:
            row = await self.repo.get_member_row(profile.id)
            member = row
        bindings = await RBACService(self.db).get_user_bindings(user_id)
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "member": member,
            "bindings": bindings,
            "authorization_version": user.authorization_version,
        }

    # ------------------------------------------------------------------ 峰

    async def list_peaks(self, active_only: bool, skip: int, limit: int) -> list[Peak]:
        return await self.repo.list_peaks(
            active_only=active_only, skip=skip, limit=limit
        )

    async def count_peaks(self, active_only: bool) -> int:
        return await self.repo.count_peaks(active_only=active_only)

    async def create_peak(self, data: dict) -> Peak:
        if await self.repo.get_peak_by_code(data["code"]):
            raise ConflictException(message="峰标识已存在", details={"code": data["code"]})
        peak = Peak(**data)
        self.db.add(peak)
        await self.db.flush()
        await self.db.refresh(peak)
        # 峰组织账户与峰同事务建立（零余额）
        await self.repo_wallet.ensure_peak_account(peak.id)
        return peak

    async def update_peak(self, peak_id: int, data: dict) -> Peak:
        peak = await self.repo.get_peak_by_id(peak_id)
        if peak is None:
            raise NotFoundException(
                message="峰不存在", resource_type="peak", resource_id=peak_id
            )
        for field in ("name", "fantasy_name", "description", "is_active"):
            if field in data and data[field] is not None:
                setattr(peak, field, data[field])
        peak.version += 1
        await self.db.flush()
        return peak

    async def archive_peak(self, peak_id: int) -> Peak:
        peak = await self.repo.get_peak_by_id(peak_id)
        if peak is None:
            raise NotFoundException(
                message="峰不存在", resource_type="peak", resource_id=peak_id
            )
        active_members = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(MemberProfile)
                    .where(
                        MemberProfile.peak_id == peak_id,
                        MemberProfile.membership_status == "active",
                    )
                )
            ).scalar_one()
        )
        if active_members:
            raise ConflictException(
                message="峰仍有在册成员，不能归档",
                details={"active_members": active_members},
            )
        balance = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(WalletAccount.balance), 0)).where(
                        WalletAccount.kind == "peak",
                        WalletAccount.owner_peak_id == peak_id,
                    )
                )
            ).scalar_one()
        )
        if balance:
            raise ConflictException(
                message="峰账户仍有余额，不能归档",
                details={"balance": balance},
            )
        peak.is_active = False
        peak.archived_at = now_utc()
        peak.version += 1
        await self.db.flush()
        return peak

    # ------------------------------------------------------------------ 成员

    async def require_global_scope(self, actor: User) -> None:
        """组织历史等跨峰读需要全范围；峰范围账号一律拒绝。"""
        if await self._allowed_peak_ids(actor) is not None:
            raise AuthorizationException(
                message="需要全范围组织权限",
                error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
            )

    async def list_members(
        self,
        actor: User,
        *,
        keyword: Optional[str],
        peak_id: Optional[int],
        membership_status: Optional[str],
        skip: int,
        limit: int,
    ) -> tuple[list[dict], int]:
        allowed = await self._allowed_peak_ids(actor)
        if peak_id is not None:
            self._ensure_in_scope(peak_id, allowed)
        rows = await self.repo.list_member_rows(
            peak_ids=allowed,
            keyword=keyword,
            peak_id=peak_id,
            membership_status=membership_status,
            skip=skip,
            limit=limit,
        )
        total = await self.repo.count_members(
            peak_ids=allowed,
            keyword=keyword,
            peak_id=peak_id,
            membership_status=membership_status,
        )
        return rows, total

    async def get_member(self, actor: User, member_id: int) -> dict:
        member = await self.repo.get_member_row(member_id)
        if member is None:
            raise NotFoundException(
                message="成员不存在", resource_type="member", resource_id=member_id
            )
        allowed = await self._allowed_peak_ids(actor)
        self._ensure_in_scope(member["peak_id"], allowed)
        return member

    async def create_member(
        self, actor: User, *, user_id: int, peak_id: Optional[int], student_id: Optional[str]
    ) -> dict:
        allowed = await self._allowed_peak_ids(actor)
        if peak_id is not None:
            self._ensure_in_scope(peak_id, allowed)
        user = (
            await self.db.execute(
                select(User).where(User.id == user_id, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundException(
                message="用户不存在", resource_type="user", resource_id=user_id
            )
        if await self.repo.get_member_by_user_id(user_id):
            raise ConflictException(message="该用户已有成员档案")
        profile = MemberProfile(
            user_id=user_id,
            peak_id=peak_id,
            student_id=student_id,
            membership_status="active",
        )
        self.db.add(profile)
        await self.db.flush()
        return await self.repo.get_member_row(profile.id)

    async def update_member(self, actor: User, member_id: int, data: dict) -> dict:
        member = await self.get_member(actor, member_id)
        profile = (
            await self.db.execute(
                select(MemberProfile).where(MemberProfile.id == member_id)
            )
        ).scalar_one()
        allowed = await self._allowed_peak_ids(actor)
        if "peak_id" in data and data["peak_id"] is not None:
            self._ensure_in_scope(data["peak_id"], allowed)
        for field in ("student_id", "peak_id", "membership_status"):
            if field in data and data[field] is not None:
                setattr(profile, field, data[field])
        profile.version += 1
        await self.db.flush()
        return await self.repo.get_member_row(member_id)

    async def move_member(self, actor: User, member_id: int, peak_id: Optional[int]) -> dict:
        await self.get_member(actor, member_id)
        allowed = await self._allowed_peak_ids(actor)
        if peak_id is not None:
            self._ensure_in_scope(peak_id, allowed)
        profile = (
            await self.db.execute(
                select(MemberProfile).where(MemberProfile.id == member_id)
            )
        ).scalar_one()
        profile.peak_id = peak_id
        profile.version += 1
        await self.db.flush()
        return await self.repo.get_member_row(member_id)

    async def remove_member(self, actor: User, member_id: int) -> dict:
        member = await self.get_member(actor, member_id)
        balance = await self.repo.user_wallet_balance(member["user_id"])
        if balance:
            raise ConflictException(
                message="成员钱包仍有余额，需先结清",
                details={"balance": balance},
            )
        active_claims = await self.repo.active_claim_count(member["user_id"])
        if active_claims:
            raise ConflictException(
                message="成员仍有执行中任务，需先结清",
                details={"active_claims": active_claims},
            )
        profile = (
            await self.db.execute(
                select(MemberProfile).where(MemberProfile.id == member_id)
            )
        ).scalar_one()
        profile.membership_status = "left"
        profile.left_at = now_utc()
        profile.version += 1
        # 撤销默认 member 绑定（保留其他显式授权，由授权管理员单独处理）
        from app.models.role import Role

        role_row = (
            await self.db.execute(select(Role).where(Role.name == "member"))
        ).scalar_one_or_none()
        if role_row is not None:
            await self.rbac_repo.delete_user_bindings(member["user_id"], role_row.id)
        await self.db.flush()
        return await self.repo.get_member_row(member_id)