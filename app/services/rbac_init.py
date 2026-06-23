"""
RBAC系统初始化模块
负责在应用启动时初始化权限、角色和默认管理员账号
"""

from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.core.loguru_logger import get_logger
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.repositories.user_repo import UserRepository
from app.repositories.rbac_repo import RBACRepository

logger = get_logger("rbac_init")


class RBACInitializer:
    """RBAC系统初始化器"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.logger = get_logger("rbac_init")
    
    async def initialize_rbac_system(self, admin_username: str,
                                   admin_email: str,
                                   admin_password: str) -> Dict[str, any]:
        """
        初始化RBAC系统，包括权限、角色和默认管理员账号
        
        Args:
            admin_username: 管理员用户名
            admin_email: 管理员邮箱
            admin_password: 管理员密码
            
        Returns:
            初始化结果
        """
        result = {
            "success": False,
            "permissions_created": 0,
            "roles_created": 0,
            "admin_created": False,
            "errors": []
        }
        
        try:
            # 1. 创建默认权限
            self.logger.info("开始创建默认权限")
            permissions_created = await self._create_default_permissions()
            result["permissions_created"] = len(permissions_created)
            self.logger.info(f"创建了 {len(permissions_created)} 个默认权限")
            
            # 2. 创建默认角色
            self.logger.info("开始创建默认角色")
            roles_created = await self._create_default_roles(permissions_created)
            result["roles_created"] = len(roles_created)
            self.logger.info(f"创建了 {len(roles_created)} 个默认角色")
            
            # 3. 创建默认管理员账号
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
        """创建默认权限"""
        # 定义系统默认权限
        default_permissions = [
            # 用户管理权限
            {"name": "user:create", "resource": "user", "action": "create", "description": "创建用户"},
            {"name": "user:read", "resource": "user", "action": "read", "description": "查看用户"},
            {"name": "user:update", "resource": "user", "action": "update", "description": "更新用户"},
            {"name": "user:delete", "resource": "user", "action": "delete", "description": "删除用户"},
            {"name": "user:list", "resource": "user", "action": "list", "description": "列出用户"},
            {"name": "user:manage_roles", "resource": "user", "action": "manage_roles", "description": "管理用户角色"},
            
            # 角色管理权限
            {"name": "role:create", "resource": "role", "action": "create", "description": "创建角色"},
            {"name": "role:read", "resource": "role", "action": "read", "description": "查看角色"},
            {"name": "role:update", "resource": "role", "action": "update", "description": "更新角色"},
            {"name": "role:delete", "resource": "role", "action": "delete", "description": "删除角色"},
            {"name": "role:list", "resource": "role", "action": "list", "description": "列出角色"},
            {"name": "role:manage_permissions", "resource": "role", "action": "manage_permissions", "description": "管理角色权限"},
            
            # 权限管理权限
            {"name": "permission:create", "resource": "permission", "action": "create", "description": "创建权限"},
            {"name": "permission:read", "resource": "permission", "action": "read", "description": "查看权限"},
            {"name": "permission:update", "resource": "permission", "action": "update", "description": "更新权限"},
            {"name": "permission:delete", "resource": "permission", "action": "delete", "description": "删除权限"},
            {"name": "permission:list", "resource": "permission", "action": "list", "description": "列出权限"},
            
            # 系统管理权限
            {"name": "system:config", "resource": "system", "action": "config", "description": "系统配置"},
            {"name": "system:monitor", "resource": "system", "action": "monitor", "description": "系统监控"},
            {"name": "system:logs", "resource": "system", "action": "logs", "description": "查看系统日志"},
            
            # 异常管理权限
            {"name": "exception:read", "resource": "exception", "action": "read", "description": "查看异常日志"},
            {"name": "exception:delete", "resource": "exception", "action": "delete", "description": "删除异常日志"},
            {"name": "exception:analyze", "resource": "exception", "action": "analyze", "description": "分析异常"},
            
            # API访问权限
            {"name": "api:access", "resource": "api", "action": "access", "description": "访问API"},
            {"name": "api:docs", "resource": "api", "action": "docs", "description": "查看API文档"},
        ]
        
        created_permissions = []
        
        for perm_data in default_permissions:
            # 检查权限是否已存在
            existing_perm = await self.rbac_repo.get_permission_by_resource_and_action(
                perm_data["resource"], perm_data["action"]
            )
            
            if not existing_perm:
                permission = Permission(
                    name=perm_data["name"],
                    resource=perm_data["resource"],
                    action=perm_data["action"],
                    description=perm_data["description"]
                )
                self.db.add(permission)
                created_permissions.append(permission)
                self.logger.debug(f"创建权限: {perm_data['resource']}:{perm_data['action']}")
            else:
                created_permissions.append(existing_perm)
                self.logger.debug(f"权限已存在: {perm_data['resource']}:{perm_data['action']}")
        
        await self.db.commit()
        return created_permissions
    
    async def _create_default_roles(self, permissions: List[Permission]) -> List[Role]:
        """创建默认角色"""
        # 创建权限映射，便于查找
        permission_map = {}
        for perm in permissions:
            key = f"{perm.resource}:{perm.action}"
            permission_map[key] = perm
        
        # 定义默认角色及其权限
        default_roles = [
            {
                "name": "admin",
                "description": "系统管理员，拥有所有权限",
                "permissions": list(permission_map.keys())  # 所有权限
            },
            {
                "name": "user_manager",
                "description": "用户管理员，负责管理用户",
                "permissions": [
                    "user:create", "user:read", "user:update", "user:list", "user:manage_roles",
                    "role:read", "role:list",
                    "permission:read", "permission:list",
                    "api:access", "api:docs"
                ]
            },
            {
                "name": "developer",
                "description": "开发者，可以查看系统信息和API文档",
                "permissions": [
                    "user:read", "user:list",
                    "role:read", "role:list",
                    "permission:read", "permission:list",
                    "system:monitor",
                    "exception:read", "exception:analyze",
                    "api:access", "api:docs"
                ]
            },
            {
                "name": "user",
                "description": "普通用户，基本权限",
                "permissions": [
                    "api:access"
                ]
            },
            {
                "name": "guest",
                "description": "访客，最低权限",
                "permissions": [
                    "api:access"
                ]
            }
        ]
        
        created_roles = []
        
        for role_data in default_roles:
            # 检查角色是否已存在
            existing_role = await self.rbac_repo.get_role_by_name(role_data["name"])
            
            if not existing_role:
                role = Role(
                    name=role_data["name"],
                    description=role_data["description"]
                )
                
                # 添加权限
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
    
    async def _create_admin_user(self, username: str, email: str, 
                               password: str, roles: List[Role]) -> bool:
        """创建默认管理员用户"""
        # 检查管理员是否已存在
        existing_admin = await self.user_repo.get_by_username(username)
        if existing_admin:
            self.logger.info(f"管理员账号 '{username}' 已存在")
            return False
        
        # 获取管理员角色
        admin_role = None
        for role in roles:
            if role.name == "admin":
                admin_role = role
                break
        
        if not admin_role:
            self.logger.error("未找到管理员角色")
            return False
        
        # 创建管理员用户
        admin_user = User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            is_active=True,
            is_superuser=True
        )
        
        # 添加管理员角色
        admin_user.roles.append(admin_role)
        
        self.db.add(admin_user)
        await self.db.commit()
        
        self.logger.info(f"管理员账号创建成功: {username}")
        return True


async def initialize_rbac(db: AsyncSession) -> Dict[str, any]:
    """
    初始化RBAC系统的便捷函数

    管理员凭据来自配置：ADMIN_USERNAME / ADMIN_EMAIL / ADMIN_PASSWORD。
    未配置 ADMIN_PASSWORD 时随机生成一个强密码，并仅在确实创建了管理员时
    通过返回值回传明文（供启动流程提示一次），绝不在本函数内打印明文。

    Args:
        db: 数据库会话

    Returns:
        初始化结果
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

    # 仅当本次确实创建了管理员、且密码是自动生成的，才回传明文供启动日志提示一次
    if result.get("admin_created") and generated:
        result["admin_password_generated"] = True
        result["generated_admin_password"] = password
    else:
        result["admin_password_generated"] = False

    return result


# ---------------------------------------------------------------------------
# 启动任务：RBAC seed（权限 / 角色 / 默认管理员）
# ---------------------------------------------------------------------------
# 原散落在 main.py 的 _initialize_rbac，现收敛到本模块并以 @register_startup 自注册。
# 依赖 DB 已就绪 → priority=20 紧随 schema 初始化（priority=10）之后。

from app.core.lifecycle import register_startup  # noqa: E402


@register_startup("rbac_seed", priority=20, critical=False)
async def startup_rbac_seed() -> None:
    """启动任务：初始化 RBAC 权限系统（幂等：查重再插，已存在即跳过）。

    critical=False：seed 失败不阻断启动（仅记 error）——与原 main.py 行为一致，
    避免初始化数据问题导致整个服务无法启动。DB 未就绪会在 DB 任务阶段先 fail。
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
                        # 自动生成的初始密码仅在确实创建管理员时提示一次
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