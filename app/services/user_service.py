"""用户管理服务：负责用户 CRUD（列表/查询/更新/删除）。

职责边界：
- 本服务只管用户实体本身的增删改查与字段校验（邮箱查重、密码哈希）。
- 认证、token 签发/轮换/撤销归 AuthService，不在本服务范围内。
- 通过构造函数注入 UserRepository，便于测试与组合。
"""

from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.core.security import get_password_hash
from app.models.user import User
from app.repositories.user_repo import UserRepository


class UserService:
    """用户管理服务（CRUD）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    async def list_users(self, skip: int = 0, limit: int = 100) -> Tuple[list, int]:
        """分页获取用户列表，返回 (users, total)。"""
        users = await self.user_repo.get_all(skip=skip, limit=limit)
        total = await self.user_repo.count()
        return users, total

    async def get_user(self, user_id: int) -> User:
        """获取指定用户；不存在抛 NotFoundException。"""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=user_id,
            )
        return user

    async def update_user(self, user_id: int, update_data: dict) -> User:
        """更新指定用户字段。

        - update_data: 仅含允许更新字段（email/full_name/password/is_active）的非 None 项。
        - 邮箱变更时做查重；密码变更时做哈希。
        """
        user = await self.get_user(user_id)
        email_conflicts = await self._email_conflicts(user_id, update_data)
        self._apply_update(user, update_data, email_conflicts)
        return await self.user_repo.update(user)

    async def update_profile(self, user: User, update_data: dict) -> User:
        """当前用户自助更新个人资料（不允许通过此途径改 is_active）。

        - user: 当前登录用户对象。
        - update_data: 仅含允许字段（email/full_name/password）的非 None 项。
        """
        email_conflicts = await self._email_conflicts(user.id, update_data)
        self._apply_update(
            user, update_data,
            email_conflicts=email_conflicts,
            allow_active=False,
        )
        return await self.user_repo.update(user)

    async def delete_user(self, user_id: int, current_user_id: int) -> None:
        """删除用户。禁止自删（抛 ConflictException）；不存在抛 NotFoundException。"""
        if user_id == current_user_id:
            raise ConflictException(
                message="不能删除自己",
                details={"user_id": user_id},
            )
        success = await self.user_repo.delete(user_id)
        if not success:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=user_id,
            )

    # ------------------------------------------------------------------ 内部

    async def _email_conflicts(self, self_id: int, update_data: dict) -> bool:
        """update_data 中若包含 email，检查是否与他人冲突。"""
        email = update_data.get("email")
        if email is None:
            return False
        existing = await self.user_repo.get_by_email(email)
        return existing is not None and existing.id != self_id

    @staticmethod
    def _apply_update(
        user: User,
        update_data: dict,
        email_conflicts: bool,
        allow_active: bool = True,
    ) -> None:
        """把 update_data 的字段就地应用到 user 对象。

        - email_conflicts: 调用方预先算好的邮箱冲突结果；冲突则抛 ConflictException。
        - allow_active: 是否允许设置 is_active（自助资料更新禁止）。
        """
        if email_conflicts:
            raise ConflictException(
                message="邮箱已被其他用户使用",
                details={"email": update_data.get("email")},
            )

        if "email" in update_data and update_data["email"] is not None:
            user.email = update_data["email"]
        if "full_name" in update_data:
            user.full_name = update_data["full_name"]
        if update_data.get("password") is not None:
            user.hashed_password = get_password_hash(update_data["password"])
        if allow_active and update_data.get("is_active") is not None:
            user.is_active = update_data["is_active"]
