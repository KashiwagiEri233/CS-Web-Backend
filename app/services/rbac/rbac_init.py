"""RBAC 系统初始化：权限 / 角色 / 默认管理员 seed。

默认权限与角色定义见 ``rbac_seed_data``；本模块负责编排与启动任务注册。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.lifecycle import register_startup
from app.core.loguru_logger import get_logger
from app.core.security import async_get_password_hash
from app.models.organization import MemberProfile
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User, user_roles
from app.repositories.rbac_repo import RBACRepository
from app.repositories.user_repo import UserRepository
from app.services.rbac.rbac_seed_data import (
    ADMIN_ROLE_NAME,
    DEFAULT_MEMBER_ROLE_NAME,
    DEFAULT_PERMISSIONS,
    ROLE_SCOPE_POLICY,
    build_default_roles,
)

logger = get_logger("rbac_init")

# PostgreSQL advisory transaction lock：保证多 worker 只执行一份 RBAC seed。
_RBAC_SEED_LOCK_KEY = 873924002


class RBACInitializer:
    """RBAC 系统初始化器"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.logger = get_logger("rbac_init")

    async def initialize_rbac_system(
        self,
        admin_username: str,
        admin_email: str,
        admin_password: Optional[str],
    ) -> Dict[str, Any]:
        """初始化 RBAC 系统（权限、角色、默认管理员）。

        Returns:
            初始化结果 dict。
        """
        result: Dict[str, Any] = {
            "success": False,
            "permissions_created": 0,
            "roles_created": 0,
            "admin_created": False,
            "errors": [],
        }

        try:
            self.logger.info("开始创建默认权限")
            permissions, permissions_created = await self._create_default_permissions()
            result["permissions_created"] = permissions_created
            self.logger.info(f"创建了 {permissions_created} 个默认权限")

            self.logger.info("开始创建默认角色")
            roles, roles_created = await self._create_default_roles(permissions)
            result["roles_created"] = roles_created
            self.logger.info(f"创建了 {roles_created} 个默认角色")

            self.logger.info("开始补齐成员档案与默认 member 绑定")
            await self._ensure_member_baseline(roles)

            self.logger.info("开始创建默认管理员账号")
            admin_created = await self._create_admin_user(
                admin_username, admin_email, admin_password, roles
            )
            result["admin_created"] = admin_created
            if admin_created:
                self.logger.info(f"成功创建管理员账号: {admin_username}")
            else:
                self.logger.info("管理员账号已存在，无需重复创建")

            result["success"] = True
            self.logger.info("RBAC系统初始化完成")

        except Exception as e:
            await self.db.rollback()
            error_msg = f"RBAC系统初始化失败: {str(e)}"
            self.logger.error(error_msg)
            result["errors"].append(error_msg)

        return result

    async def _create_default_permissions(self) -> Tuple[List[Permission], int]:
        """创建默认权限并返回完整集合；只统计本次实际新增数量。"""
        permissions: List[Permission] = []
        created_count = 0

        for perm_data in DEFAULT_PERMISSIONS:
            existing_perm = await self.rbac_repo.get_permission_by_resource_and_action(
                perm_data["resource"], perm_data["action"]
            )

            if not existing_perm:
                permission = Permission(
                    name=perm_data["name"],
                    resource=perm_data["resource"],
                    action=perm_data["action"],
                    description=perm_data["description"],
                )
                self.db.add(permission)
                permissions.append(permission)
                created_count += 1
                self.logger.debug(
                    f"创建权限: {perm_data['resource']}:{perm_data['action']}"
                )
            else:
                permissions.append(existing_perm)
                self.logger.debug(
                    f"权限已存在: {perm_data['resource']}:{perm_data['action']}"
                )

        await self.db.flush()
        return permissions, created_count

    async def _create_default_roles(
        self, permissions: List[Permission]
    ) -> Tuple[List[Role], int]:
        """创建默认角色，并为已有默认角色补齐新增权限。

        只追加 seed 新增的权限，不删除管理员后续手工授予的权限，避免启动时
        覆盖业务配置。
        """
        permission_map = {
            f"{perm.resource}:{perm.action}": perm for perm in permissions
        }
        default_roles = build_default_roles(list(permission_map.keys()))
        roles: List[Role] = []
        created_count = 0

        for role_data in default_roles:
            existing_role = await self.rbac_repo.get_role_by_name(role_data["name"])

            if not existing_role:
                role = Role(
                    name=role_data["name"],
                    description=role_data["description"],
                    display_name=role_data.get("display_name"),
                    fantasy_display_name=role_data.get("fantasy_display_name"),
                    audit_domains=role_data.get("audit_domains") or [],
                    is_system=role_data.get("is_system", False),
                )
                for perm_key in role_data["permissions"]:
                    if perm_key in permission_map:
                        role.permissions.append(permission_map[perm_key])
                self.db.add(role)
                roles.append(role)
                created_count += 1
                self.logger.debug(f"创建角色: {role_data['name']}")
            else:
                loaded_role = await self.rbac_repo.get_role_with_permissions(
                    existing_role.id
                )
                if loaded_role is None:
                    raise RuntimeError(f"角色读取失败: {role_data['name']}")
                # 种子管理的展示字段保持一致（不覆盖权限的运行时增删）
                loaded_role.display_name = role_data.get("display_name")
                loaded_role.fantasy_display_name = role_data.get("fantasy_display_name")
                loaded_role.audit_domains = role_data.get("audit_domains") or []
                loaded_role.description = role_data["description"]
                loaded_role.is_system = role_data.get("is_system", False)
                assigned_keys = {
                    f"{perm.resource}:{perm.action}" for perm in loaded_role.permissions
                }
                for perm_key in role_data["permissions"]:
                    if perm_key not in assigned_keys and perm_key in permission_map:
                        loaded_role.permissions.append(permission_map[perm_key])
                roles.append(loaded_role)
                self.logger.debug(f"角色已存在: {role_data['name']}")

        await self.db.flush()
        return roles, created_count

    async def _create_admin_user(
        self,
        username: str,
        email: str,
        password: Optional[str],
        roles: List[Role],
    ) -> bool:
        """创建默认管理员用户；已存在则返回 False。"""
        existing_admin = await self.user_repo.get_by_username(username)
        if existing_admin:
            self.logger.info(f"管理员账号 '{username}' 已存在")
            return False

        if not password:
            raise RuntimeError(
                "首次创建管理员前必须配置 ADMIN_PASSWORD；"
                "框架不会生成或记录明文管理员密码"
            )

        admin_role = next((r for r in roles if r.name == ADMIN_ROLE_NAME), None)
        if not admin_role:
            self.logger.error("未找到管理员角色")
            return False

        admin_user = User(
            username=username,
            email=email,
            hashed_password=await async_get_password_hash(password),
            is_active=True,
            is_superuser=True,
        )
        self.db.add(admin_user)
        await self.db.flush()
        # 显式写入 all 范围绑定：user_roles 的默认范围是 own（最小权限）
        await self.db.execute(
            insert(user_roles).values(
                user_id=admin_user.id,
                role_id=admin_role.id,
                scope_type="all",
                created_by=None,
            )
        )

        self.logger.info(f"管理员账号创建成功: {username}")
        return True

    async def _ensure_member_baseline(self, roles: List[Role]) -> None:
        """为存量用户补齐 active 成员档案与默认 member 绑定（幂等）。

        - 已有档案不覆盖（避免启动重置用户资料/峰归属）。
        - 已有 member 绑定不重复插入。
        - 不复活禁用/软删用户，仅补结构与绑定。
        """
        member_role = next(
            (r for r in roles if r.name == DEFAULT_MEMBER_ROLE_NAME), None
        )
        if member_role is None:
            return
        user_ids = (
            (
                await self.db.execute(
                    select(User.id).where(User.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        if not user_ids:
            return

        existing_profiles = set(
            (
                await self.db.execute(
                    select(MemberProfile.user_id).where(
                        MemberProfile.user_id.in_(user_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in user_ids:
            if user_id not in existing_profiles:
                self.db.add(MemberProfile(user_id=user_id, membership_status="active"))

        existing_member_bindings = set(
            (
                await self.db.execute(
                    select(user_roles.c.user_id).where(
                        user_roles.c.user_id.in_(user_ids),
                        user_roles.c.role_id == member_role.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        rows = [
            {
                "user_id": user_id,
                "role_id": member_role.id,
                "scope_type": next(iter(ROLE_SCOPE_POLICY["member"]), "own"),
                "created_by": None,
            }
            for user_id in user_ids
            if user_id not in existing_member_bindings
        ]
        if rows:
            await self.db.execute(insert(user_roles), rows)
        await self.db.flush()


async def initialize_rbac(db: AsyncSession) -> Dict[str, Any]:
    """初始化 RBAC 系统的便捷函数。

    管理员凭据来自配置：ADMIN_USERNAME / ADMIN_EMAIL / ADMIN_PASSWORD。
    管理员已存在时无需密码；首次创建时必须显式配置 ``ADMIN_PASSWORD``。
    框架不会生成、返回或记录明文管理员密码。
    """
    from app.core.config import settings

    initializer = RBACInitializer(db)
    return await initializer.initialize_rbac_system(
        admin_username=settings.ADMIN_USERNAME,
        admin_email=settings.ADMIN_EMAIL,
        admin_password=settings.ADMIN_PASSWORD,
    )


@register_startup("rbac_seed", priority=20, critical=True)
async def startup_rbac_seed() -> None:
    """在集群锁下原子初始化 RBAC 权限系统。

    权限系统是鉴权基础设施，seed 失败会拒绝启动，避免实例以不完整权限集提供服务。
    依赖 DB 已就绪 → priority=20 紧随 schema 初始化（priority=10）之后。
    """
    from app.core.config import settings
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _RBAC_SEED_LOCK_KEY},
        )
        init_result = await initialize_rbac(db)
        if not init_result["success"]:
            raise RuntimeError("RBAC seed 失败: " + "; ".join(init_result["errors"]))

        await db.commit()
        logger.info(
            "RBAC系统初始化成功",
            permissions_created=init_result["permissions_created"],
            roles_created=init_result["roles_created"],
            admin_created=init_result["admin_created"],
        )
        if init_result["admin_created"]:
            logger.info(
                "默认管理员已创建（密码来自 ADMIN_PASSWORD 配置，未写入日志）",
                username=settings.ADMIN_USERNAME,
            )
