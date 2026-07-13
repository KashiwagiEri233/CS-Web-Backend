"""RBAC 系统初始化：权限 / 角色 / 默认管理员 seed。

默认权限与角色定义见 ``rbac_seed_data``；本模块负责编排与启动任务注册。
"""

from __future__ import annotations

from typing import Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.lifecycle import register_startup
from app.core.loguru_logger import get_logger
from app.core.security import get_password_hash
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.repositories.rbac_repo import RBACRepository
from app.repositories.user_repo import UserRepository
from app.services.rbac_seed_data import DEFAULT_PERMISSIONS, build_default_roles

logger = get_logger("rbac_init")


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
        admin_password: str,
    ) -> Dict[str, any]:
        """初始化 RBAC 系统（权限、角色、默认管理员）。

        Returns:
            初始化结果 dict。
        """
        result = {
            "success": False,
            "permissions_created": 0,
            "roles_created": 0,
            "admin_created": False,
            "errors": [],
        }

        try:
            self.logger.info("开始创建默认权限")
            permissions_created = await self._create_default_permissions()
            result["permissions_created"] = len(permissions_created)
            self.logger.info(f"创建了 {len(permissions_created)} 个默认权限")

            self.logger.info("开始创建默认角色")
            roles_created = await self._create_default_roles(permissions_created)
            result["roles_created"] = len(roles_created)
            self.logger.info(f"创建了 {len(roles_created)} 个默认角色")

            self.logger.info("开始创建默认管理员账号")
            admin_created = await self._create_admin_user(
                admin_username, admin_email, admin_password, roles_created
            )
            result["admin_created"] = admin_created
            if admin_created:
                self.logger.info(f"成功创建管理员账号: {admin_username}")
            else:
                self.logger.warning("管理员账号已存在或创建失败")

            result["success"] = True
            self.logger.info("RBAC系统初始化完成")

        except Exception as e:
            error_msg = f"RBAC系统初始化失败: {str(e)}"
            self.logger.error(error_msg)
            result["errors"].append(error_msg)

        return result

    async def _create_default_permissions(self) -> List[Permission]:
        """创建默认权限（幂等：已存在则复用）。"""
        created_permissions: List[Permission] = []

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
                created_permissions.append(permission)
                self.logger.debug(
                    f"创建权限: {perm_data['resource']}:{perm_data['action']}"
                )
            else:
                created_permissions.append(existing_perm)
                self.logger.debug(
                    f"权限已存在: {perm_data['resource']}:{perm_data['action']}"
                )

        await self.db.commit()
        return created_permissions

    async def _create_default_roles(self, permissions: List[Permission]) -> List[Role]:
        """创建默认角色（幂等：已存在则复用）。"""
        permission_map = {f"{perm.resource}:{perm.action}": perm for perm in permissions}
        default_roles = build_default_roles(list(permission_map.keys()))
        created_roles: List[Role] = []

        for role_data in default_roles:
            existing_role = await self.rbac_repo.get_role_by_name(role_data["name"])

            if not existing_role:
                role = Role(
                    name=role_data["name"],
                    description=role_data["description"],
                )
                for perm_key in role_data["permissions"]:
                    if perm_key in permission_map:
                        role.permissions.append(permission_map[perm_key])
                self.db.add(role)
                created_roles.append(role)
                self.logger.debug(f"创建角色: {role_data['name']}")
            else:
                created_roles.append(existing_role)
                self.logger.debug(f"角色已存在: {role_data['name']}")

        await self.db.commit()
        return created_roles

    async def _create_admin_user(
        self,
        username: str,
        email: str,
        password: str,
        roles: List[Role],
    ) -> bool:
        """创建默认管理员用户；已存在则返回 False。"""
        existing_admin = await self.user_repo.get_by_username(username)
        if existing_admin:
            self.logger.info(f"管理员账号 '{username}' 已存在")
            return False

        admin_role = next((r for r in roles if r.name == "admin"), None)
        if not admin_role:
            self.logger.error("未找到管理员角色")
            return False

        admin_user = User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            is_active=True,
            is_superuser=True,
        )
        admin_user.roles.append(admin_role)

        self.db.add(admin_user)
        await self.db.commit()

        self.logger.info(f"管理员账号创建成功: {username}")
        return True


async def initialize_rbac(db: AsyncSession) -> Dict[str, any]:
    """初始化 RBAC 系统的便捷函数。

    管理员凭据来自配置：ADMIN_USERNAME / ADMIN_EMAIL / ADMIN_PASSWORD。
    未配置 ADMIN_PASSWORD 时随机生成强密码，并仅在确实创建了管理员时
    通过返回值回传明文（供启动流程提示一次），绝不在本函数内打印明文。
    """
    import secrets

    from app.core.config import settings

    generated = False
    password = settings.ADMIN_PASSWORD
    if not password:
        password = secrets.token_urlsafe(16)
        generated = True

    initializer = RBACInitializer(db)
    result = await initializer.initialize_rbac_system(
        admin_username=settings.ADMIN_USERNAME,
        admin_email=settings.ADMIN_EMAIL,
        admin_password=password,
    )

    if result.get("admin_created") and generated:
        result["admin_password_generated"] = True
        result["generated_admin_password"] = password
    else:
        result["admin_password_generated"] = False

    return result


@register_startup("rbac_seed", priority=20, critical=False)
async def startup_rbac_seed() -> None:
    """启动任务：初始化 RBAC 权限系统（幂等：查重再插，已存在即跳过）。

    critical=False：seed 失败不阻断启动（仅记 error）。
    依赖 DB 已就绪 → priority=20 紧随 schema 初始化（priority=10）之后。
    """
    from app.core.config import settings
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            init_result = await initialize_rbac(db)
            if init_result["success"]:
                logger.info(
                    "RBAC系统初始化成功",
                    permissions_created=init_result["permissions_created"],
                    roles_created=init_result["roles_created"],
                    admin_created=init_result["admin_created"],
                )
                if init_result["admin_created"]:
                    if init_result.get("admin_password_generated"):
                        logger.warning(
                            "默认管理员已创建，初始密码为随机生成，请立即登录并修改（仅显示这一次）",
                            username=settings.ADMIN_USERNAME,
                            password=init_result["generated_admin_password"],
                        )
                    else:
                        logger.info(
                            "默认管理员已创建（密码来自 ADMIN_PASSWORD 配置，未写入日志）",
                            username=settings.ADMIN_USERNAME,
                        )
            else:
                logger.error("RBAC系统初始化失败", errors=init_result["errors"])
        except Exception as e:  # noqa: BLE001 - seed 失败不阻断启动
            logger.error(f"RBAC系统初始化异常: {str(e)}")
