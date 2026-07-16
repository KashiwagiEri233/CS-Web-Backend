"""RBAC 用户/角色/权限关联编排。

作为 ``RBACService`` 的职责 mixin，仅承载关联变更；公共入口仍是
``app.services.rbac_service.RBACService``。
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PermissionDeniedException
from app.models.role import Role
from app.models.user import User
from app.repositories.rbac_repo import RBACRepository
from app.services.rbac_seed_data import ADMIN_ROLE_NAME


class RBACAssignmentMixin:
    """用户角色和角色权限的授予/撤销能力。"""

    db: AsyncSession
    rbac_repo: RBACRepository

    async def _invalidate_user_perm_cache(self, user_id: int) -> None:
        raise NotImplementedError

    async def _invalidate_role_users_perm_cache(self, role_id: int) -> None:
        raise NotImplementedError

    async def user_exists(self, user_id: int) -> bool:
        """判断用户是否存在。"""
        return await self.rbac_repo.get_user_by_id(user_id) is not None

    async def grant_role_to_user(
        self,
        user_id: int,
        role_id: int,
        commit: bool = True,
        actor: Optional[User] = None,
    ) -> bool:
        """为用户授予角色。

        提权防护：授予内置 admin 角色、或目标用户为超级用户时，要求 actor
        是超级用户；actor=None 视为可信内部调用（如种子初始化），放行。
        """
        user = await self.rbac_repo.get_user_with_roles(user_id)
        role = await self.rbac_repo.get_role_by_id(role_id)
        if not user or not role:
            return False
        self._check_privilege_escalation(user, role, actor)

        if not any(item.id == role.id for item in user.roles):
            user.roles.append(role)
            if commit:
                await self.db.commit()
            await self._invalidate_user_perm_cache(user_id)
        return True

    async def revoke_role_from_user(
        self,
        user_id: int,
        role_id: int,
        commit: bool = True,
        actor: Optional[User] = None,
    ) -> bool:
        """从用户撤销角色。提权防护同 grant_role_to_user。"""
        user = await self.rbac_repo.get_user_with_roles(user_id)
        if not user:
            return False

        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return False
        self._check_privilege_escalation(user, role, actor)

        target = next((item for item in user.roles if item.id == role.id), None)
        if target is not None:
            user.roles.remove(target)
            if commit:
                await self.db.commit()
            await self._invalidate_user_perm_cache(user_id)
        return True

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _check_privilege_escalation(
        user: User, role: Role, actor: Optional[User]
    ) -> None:
        """阻止非超级用户借角色分配提权（授 admin）或操纵超级用户的角色。"""
        if actor is None or actor.is_superuser:
            return
        if role.name == ADMIN_ROLE_NAME or user.is_superuser:
            raise PermissionDeniedException(required_permissions=["superuser"])

    async def grant_permission_to_role(
        self, role_id: int, permission_id: int, commit: bool = True
    ) -> bool:
        """为角色授予权限。"""
        role = await self.rbac_repo.get_role_with_permissions(role_id)
        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        if not role or not permission:
            return False

        if permission not in role.permissions:
            role.permissions.append(permission)
            if commit:
                await self.db.commit()
            await self._invalidate_role_users_perm_cache(role_id)
        return True

    async def revoke_permission_from_role(
        self, role_id: int, permission_id: int, commit: bool = True
    ) -> bool:
        """从角色撤销权限。"""
        role = await self.rbac_repo.get_role_with_permissions(role_id)
        if not role:
            return False

        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        if not permission:
            return False

        if permission in role.permissions:
            role.permissions.remove(permission)
            if commit:
                await self.db.commit()
            await self._invalidate_role_users_perm_cache(role_id)
        return True
