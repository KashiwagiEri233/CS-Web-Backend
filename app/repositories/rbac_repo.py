from typing import List, Optional, Sequence, Set

from sqlalchemy import select, func, delete, insert, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User, UserRoleBinding, user_roles
from app.models.organization import Peak
from app.models.role import Role, role_permissions
from app.models.permission import Permission
from app.repositories.base import paginate
from app.repositories.user_repo import UserRepository


class RBACRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ 鉴权热路径
    # 下面两个方法直接查出判定所需的最小结果集（权限串 / 角色名），不构建 ORM 对象图。
    # 对比 get_user_with_roles + selectinload：那条路径是 3 次往返（user、roles、
    # permissions）且要实例化整棵关系树，而鉴权只需要一个字符串集合——每个受保护
    # 请求都要走一遍，值得用平铺 join 换掉。

    async def get_authorization_permissions(self, user_id: int) -> Set[str]:
        """一次查询取出用户的全部有效权限串（``resource:action``）。

        与 ORM 聚合路径保持相同语义：软删用户与未启用角色都不计入。
        """
        stmt = (
            select(Permission.resource, Permission.action)
            .select_from(user_roles)
            .join(User, User.id == user_roles.c.user_id)
            .join(Role, Role.id == user_roles.c.role_id)
            .join(role_permissions, role_permissions.c.role_id == Role.id)
            .join(Permission, Permission.id == role_permissions.c.permission_id)
            .where(
                user_roles.c.user_id == user_id,
                User.deleted_at.is_(None),
                Role.is_active.is_(True),
            )
            .distinct()
        )
        result = await self.db.execute(stmt)
        return {f"{resource}:{action}" for resource, action in result.all()}

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """通过ID获取未软删用户。"""
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_with_roles(self, user_id: int) -> Optional[User]:
        """获取未软删用户及其角色（并嵌套预加载角色的权限）。

        重复实现治理波次 C2（B12）：收敛为 UserRepository 带深度参数的同一实现。
        嵌套到 roles.permissions 是必要的：权限聚合（get_user_permissions /
        check_permission）会遍历 role.permissions，否则异步下触发懒加载 -> MissingGreenlet。
        """
        return await UserRepository(self.db).get_user_with_roles(
            user_id, with_permissions=True
        )

    async def get_role_by_id(self, role_id: int) -> Optional[Role]:
        """通过ID获取角色"""
        stmt = select(Role).where(Role.id == role_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_role_by_name(self, role_name: str) -> Optional[Role]:
        """通过名称获取角色"""
        stmt = select(Role).where(Role.name == role_name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_role_with_permissions(self, role_id: int) -> Optional[Role]:
        """获取角色及其权限"""
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.id == role_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_permission_by_id(self, permission_id: int) -> Optional[Permission]:
        """通过ID获取权限"""
        stmt = select(Permission).where(Permission.id == permission_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_permission_by_name(self, name: str) -> Optional[Permission]:
        """通过名称获取权限"""
        stmt = select(Permission).where(Permission.name == name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_permission_by_resource_and_action(
        self, resource: str, action: str
    ) -> Optional[Permission]:
        """通过资源和操作获取权限"""
        stmt = select(Permission).where(
            Permission.resource == resource, Permission.action == action
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_roles(
        self, skip: int = 0, limit: Optional[int] = None
    ) -> List[Role]:
        """获取角色列表（含各自权限），可分页。limit=None 表示不分页。"""
        stmt = select(Role).options(selectinload(Role.permissions))
        if limit is not None:
            stmt = paginate(stmt, skip, limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_roles(self) -> int:
        """角色总数（用于分页 total）。"""
        result = await self.db.execute(select(func.count()).select_from(Role))
        return int(result.scalar_one())

    async def get_all_permissions(
        self, skip: int = 0, limit: Optional[int] = None
    ) -> List[Permission]:
        """获取权限列表，可分页。limit=None 表示不分页。"""
        stmt = select(Permission)
        if limit is not None:
            stmt = paginate(stmt, skip, limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_permissions(self) -> int:
        """权限总数（用于分页 total）。"""
        result = await self.db.execute(select(func.count()).select_from(Permission))
        return int(result.scalar_one())

    async def get_user_ids_by_role(self, role_id: int) -> List[int]:
        """查询拥有指定角色的全部用户 id（用于权限缓存批量失效）。"""
        result = await self.db.execute(
            select(user_roles.c.user_id).where(user_roles.c.role_id == role_id)
        )
        return [row[0] for row in result.all()]

    async def get_user_ids_by_roles(self, role_ids: Sequence[int]) -> List[int]:
        """查询拥有这批角色中任一角色的全部用户 id（去重）。

        权限定义变更会波及持有该权限的所有角色；用一条 IN 查询取回全部受影响用户，
        避免「每个角色查一次库」。
        """
        if not role_ids:
            return []
        result = await self.db.execute(
            select(user_roles.c.user_id)
            .where(user_roles.c.role_id.in_(role_ids))
            .distinct()
        )
        return [row[0] for row in result.all()]

    async def get_role_ids_by_permission(self, permission_id: int) -> List[int]:
        """查询拥有指定权限的全部角色 id（用于权限定义变更时缓存失效）。"""
        result = await self.db.execute(
            select(role_permissions.c.role_id).where(
                role_permissions.c.permission_id == permission_id
            )
        )
        return [row[0] for row in result.all()]

    async def create_role(self, role_data: dict) -> Role:
        """创建角色（flush，未 commit）。"""
        role = Role(**role_data)
        self.db.add(role)
        await self.db.flush()
        await self.db.refresh(role)
        # 预加载权限关系，避免 MissingGreenlet
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.id == role.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def create_permission(self, permission_data: dict) -> Permission:
        """创建权限（flush，未 commit）。"""
        permission = Permission(**permission_data)
        self.db.add(permission)
        await self.db.flush()
        await self.db.refresh(permission)
        stmt = (
            select(Permission)
            .options(selectinload(Permission.roles))
            .where(Permission.id == permission.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def update_role(self, role: Role, update_data: dict) -> Role:
        """更新角色字段并 flush，返回预加载权限后的角色。

        仅写入 update_data 中非 None 的字段。
        """
        for field in (
            "name",
            "display_name",
            "fantasy_display_name",
            "description",
            "audit_domains",
            "is_active",
        ):
            value = update_data.get(field)
            if value is not None:
                setattr(role, field, value)

        await self.db.flush()
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.id == role.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def delete_role(self, role_id: int) -> bool:
        """删除角色（flush，未 commit）。"""
        role = await self.get_role_by_id(role_id)
        if not role:
            return False

        await self.db.delete(role)
        await self.db.flush()
        return True

    async def update_permission(
        self, permission: Permission, update_data: dict
    ) -> Permission:
        """更新权限字段并 flush，返回预加载角色后的权限。"""
        for field in ("name", "resource", "action", "description"):
            value = update_data.get(field)
            if value is not None:
                setattr(permission, field, value)

        await self.db.flush()
        stmt = (
            select(Permission)
            .options(selectinload(Permission.roles))
            .where(Permission.id == permission.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def delete_permission(self, permission_id: int) -> bool:
        """删除权限（flush，未 commit）。"""
        permission = await self.get_permission_by_id(permission_id)
        if not permission:
            return False

        await self.db.delete(permission)
        await self.db.flush()
        return True

    async def assign_permission_to_role(self, role_id: int, permission_id: int) -> bool:
        """为角色授予权限，flush（未 commit）。"""
        role = await self.get_role_with_permissions(role_id)
        permission = await self.get_permission_by_id(permission_id)

        if not role or not permission:
            return False

        if permission not in role.permissions:
            role.permissions.append(permission)
            await self.db.flush()

        return True

    async def replace_role_permissions(
        self, role_id: int, permission_ids: Sequence[int]
    ) -> None:
        """全量替换角色权限（清空后批量授予），flush（未 commit）。"""
        role = await self.get_role_with_permissions(role_id)
        if role is None:
            return
        role.permissions = [p for p in role.permissions if p.id in permission_ids]
        if permission_ids:
            stmt = select(Permission).where(Permission.id.in_(permission_ids))
            result = await self.db.execute(stmt)
            existing = {p.id: p for p in result.scalars().all()}
            missing = [
                pid
                for pid in permission_ids
                if pid not in {p.id for p in role.permissions}
            ]
            for pid in missing:
                permission = existing.get(pid)
                if permission is not None:
                    role.permissions.append(permission)
        await self.db.flush()

    # ------------------------------------------------------------------ 角色绑定（带作用范围）

    async def get_user_bindings(self, user_id: int) -> List[dict]:
        """查询用户的全部有效角色绑定（含角色展示名）。"""
        stmt = (
            select(
                UserRoleBinding,
                Role.name,
                Role.display_name,
                Role.fantasy_display_name,
            )
            .join(Role, Role.id == UserRoleBinding.role_id)
            .where(UserRoleBinding.user_id == user_id)
            .order_by(UserRoleBinding.id)
        )
        result = await self.db.execute(stmt)
        rows = []
        for binding, role_name, display_name, fantasy_name in result.all():
            rows.append(
                {
                    "id": binding.id,
                    "role_id": binding.role_id,
                    "role_name": role_name,
                    "display_name": display_name,
                    "fantasy_display_name": fantasy_name,
                    "scope_type": binding.scope_type,
                    "scope_peak_id": binding.scope_peak_id,
                    "created_at": binding.created_at,
                }
            )
        return rows

    async def get_user_authorization_version(self, user_id: int) -> Optional[int]:
        """读取用户当前授权版本（不存在或已软删返回 None）。"""
        result = await self.db.execute(
            select(User.authorization_version).where(
                User.id == user_id, User.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def get_authorization_versions(
        self, user_ids: Sequence[int]
    ) -> dict[int, int]:
        """批量读取用户授权版本（用于按各自版本失效权限缓存）。"""
        if not user_ids:
            return {}
        result = await self.db.execute(
            select(User.id, User.authorization_version).where(User.id.in_(user_ids))
        )
        return {uid: version for uid, version in result.all()}

    async def bump_authorization_version(self, user_id: int) -> None:
        """授权变更后递增版本；缓存键与受保护写校验依赖该值。"""
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(authorization_version=User.authorization_version + 1)
        )

    async def replace_user_bindings(
        self,
        user_id: int,
        bindings: Sequence[dict],
        created_by: Optional[int] = None,
    ) -> None:
        """整组替换用户绑定（flush，不 commit）。

        调用方必须在同一外层事务内完成校验与审计；本方法不做权限判断。
        """
        await self.db.execute(delete(user_roles).where(user_roles.c.user_id == user_id))
        if bindings:
            await self.db.execute(
                insert(user_roles),
                [
                    {
                        "user_id": user_id,
                        "role_id": item["role_id"],
                        "scope_type": item["scope_type"],
                        "scope_peak_id": item.get("scope_peak_id"),
                        "created_by": created_by,
                    }
                    for item in bindings
                ],
            )
        await self.bump_authorization_version(user_id)
        await self.db.flush()

    async def get_peak_by_id(self, peak_id: int) -> Optional[Peak]:
        """读取峰（用于绑定 scope 校验）。"""
        result = await self.db.execute(select(Peak).where(Peak.id == peak_id))
        return result.scalar_one_or_none()

    async def add_user_binding(
        self,
        user_id: int,
        role_id: int,
        scope_type: str,
        scope_peak_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> None:
        """新增单条绑定并递增授权版本（flush，不 commit）。"""
        await self.db.execute(
            insert(user_roles).values(
                user_id=user_id,
                role_id=role_id,
                scope_type=scope_type,
                scope_peak_id=scope_peak_id,
                created_by=created_by,
            )
        )
        await self.bump_authorization_version(user_id)
        await self.db.flush()

    async def delete_user_bindings(self, user_id: int, role_id: int) -> None:
        """删除用户对某角色的全部绑定并递增授权版本（flush，不 commit）。"""
        await self.db.execute(
            delete(user_roles).where(
                user_roles.c.user_id == user_id, user_roles.c.role_id == role_id
            )
        )
        await self.bump_authorization_version(user_id)
        await self.db.flush()

    async def get_role_permissions_names(self, role_id: int) -> Set[str]:
        """读取角色权限名集合（用于委派上限校验）。"""
        stmt = (
            select(Permission.resource, Permission.action)
            .select_from(role_permissions)
            .join(Permission, Permission.id == role_permissions.c.permission_id)
            .where(role_permissions.c.role_id == role_id)
        )
        result = await self.db.execute(stmt)
        return {f"{resource}:{action}" for resource, action in result.all()}
