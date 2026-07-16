"""用户管理服务：负责用户 CRUD（列表/查询/更新/删除）。

职责边界：
- 本服务管用户实体增删改查与字段校验。
- 改密时在同一事务内撤销 refresh（组合 Auth/Refresh 仓储，一次 commit）。
- 删除为软删除（deleted_at），列表默认不返回已删用户。
"""

from __future__ import annotations

from typing import Tuple
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    InvalidCredentialsException,
    NotFoundException,
    ValidationException,
)
from app.core.security import async_get_password_hash, async_verify_password
from app.core.timezone import now_utc
from app.models.user import User
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository


class UserService:
    """用户管理服务（CRUD）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)

    async def list_users(self, skip: int = 0, limit: int = 100) -> Tuple[list, int]:
        """分页获取未删除用户列表，返回 (users, total)。"""
        users = await self.user_repo.list_active(skip=skip, limit=limit)
        total = await self.user_repo.count_active()
        return users, total

    async def get_user(self, user_id: int) -> User:
        """获取指定未删除用户；不存在抛 NotFoundException。"""
        user = await self.user_repo.get_by_id(user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=user_id,
            )
        return user

    async def update_user(
        self, user_id: int, update_data: dict, commit: bool = True
    ) -> User:
        """更新指定用户字段（含改密时同事务撤 refresh）。"""
        user = await self.get_user(user_id)
        email_conflicts = await self._email_conflicts(user_id, update_data)
        password_changed = await self._apply_update(user, update_data, email_conflicts)
        try:
            await self.user_repo.update(user)
            if password_changed:
                await self.refresh_repo.revoke_all_for_user(user_id)
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(message="用户名或邮箱已存在") from exc
        if commit:
            await self.db.refresh(user)
        return user

    async def update_profile(self, user: User, update_data: dict) -> User:
        """当前用户自助更新（不可改 is_active；改密需旧密码，同事务撤 refresh）。"""
        await self._verify_old_password(user, update_data)
        email_conflicts = await self._email_conflicts(user.id, update_data)
        password_changed = await self._apply_update(
            user,
            update_data,
            email_conflicts=email_conflicts,
            allow_active=False,
        )
        await self.user_repo.update(user)
        if password_changed:
            await self.refresh_repo.revoke_all_for_user(user.id)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(message="邮箱已被其他用户使用") from exc
        await self.db.refresh(user)
        return user

    async def delete_user(
        self, user_id: int, current_user_id: int, commit: bool = True
    ) -> None:
        """软删除用户。禁止自删；不存在抛 NotFoundException。

        同事务撤销全部 refresh，使会话立即失效。
        """
        if user_id == current_user_id:
            raise ConflictException(
                message="不能删除自己",
                details={"user_id": user_id},
            )
        user = await self.get_user(user_id)
        user.deleted_at = now_utc()
        user.is_active = False
        # 释放 username/email 唯一约束，便于同名重新注册。
        # username 列长 50：后缀约 21 字符，原名截断后拼接，避免 String(50) 溢出。
        stamp = int(now_utc().timestamp())
        suffix = f"__del_{user.id}_{stamp}"
        max_base = max(1, 50 - len(suffix))
        user.username = f"{user.username[:max_base]}{suffix}"
        user.email = f"del_{stamp}_{user.id}@invalid.local"
        await self.user_repo.update(user)
        await self.refresh_repo.revoke_all_for_user(user_id)
        if commit:
            await self.db.commit()

    # ------------------------------------------------------------------ 内部

    @staticmethod
    async def _verify_old_password(user: User, update_data: dict) -> None:
        """自助改密前置校验：提供新密码时必须附带正确的旧密码。

        access token 短暂泄露（XSS/日志）即可改密并吊销全部会话，旧密码校验把
        "持有 token"升级为"知道密码"，阻断该接管路径。old_password 消费后即弹出，
        不会进入字段更新流程。
        """
        old_password = update_data.pop("old_password", None)
        if update_data.get("password") is None:
            return
        if not old_password:
            raise ValidationException(
                message="修改密码必须提供当前密码",
                details={"field": "old_password"},
            )
        if not await async_verify_password(old_password, user.hashed_password):
            raise InvalidCredentialsException(
                details={"reason": "old password incorrect"}
            )

    async def _email_conflicts(self, self_id: int, update_data: dict) -> bool:
        email = update_data.get("email")
        if email is None:
            return False
        existing = await self.user_repo.get_by_email(email)
        return (
            existing is not None
            and existing.id != self_id
            and existing.deleted_at is None
        )

    @staticmethod
    async def _apply_update(
        user: User,
        update_data: dict,
        email_conflicts: bool,
        allow_active: bool = True,
    ) -> bool:
        """应用字段更新。返回是否发生了改密。"""
        if email_conflicts:
            raise ConflictException(
                message="邮箱已被其他用户使用",
                details={"email": update_data.get("email")},
            )

        password_changed = False
        if "email" in update_data and update_data["email"] is not None:
            user.email = update_data["email"]
        if "full_name" in update_data:
            user.full_name = update_data["full_name"]
        if update_data.get("password") is not None:
            user.hashed_password = await async_get_password_hash(
                update_data["password"]
            )
            user.password_changed_at = now_utc()
            password_changed = True
        if allow_active and update_data.get("is_active") is not None:
            user.is_active = update_data["is_active"]
        return password_changed
