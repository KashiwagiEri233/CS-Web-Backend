from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.base import paginate


class UserRepository(BaseRepository[User]):
    """用户仓储。通用 CRUD（get_by_id/create/update）继承自 BaseRepository，
    此处仅保留用户特有查询。"""

    model = User

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[User]:
        """分页获取未软删用户。"""
        stmt = paginate(
            select(User).where(User.deleted_at.is_(None)).order_by(User.id), skip, limit
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_active(self) -> int:
        """统计未软删用户数。"""
        stmt = select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        return int((await self.db.execute(stmt)).scalar_one())

    async def get_by_username(self, username: str) -> Optional[User]:
        """通过用户名获取未删除用户。"""
        stmt = select(User).where(
            User.username == username,
            User.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """通过邮箱获取未删除用户。"""
        stmt = select(User).where(
            User.email == email,
            User.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_github_id(self, github_id: str) -> Optional[User]:
        """通过 GitHub id 获取未删除用户（OAuth 登录）。"""
        stmt = select(User).where(
            User.github_id == github_id,
            User.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_with_roles(
        self, user_id: int, *, with_permissions: bool = False
    ) -> Optional[User]:
        """获取未删除用户及其角色（可选嵌套预加载角色的权限）。

        重复实现治理波次 C2（B12）：rbac_repo 原独立实现（嵌套 roles.permissions）
        收敛为本方法 with_permissions=True，避免同语义查询跨 repo 重复。
        """
        options = selectinload(User.roles)
        if with_permissions:
            from app.models.role import Role  # 局部导入避免循环依赖

            options = options.selectinload(Role.permissions)
        stmt = (
            select(User)
            .options(options)
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
