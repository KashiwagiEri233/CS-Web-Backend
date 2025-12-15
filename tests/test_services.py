import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import AuthService
from app.repositories.user_repo import UserRepository
from app.schemas.auth import UserCreate
from app.models.user import User


class TestAuthService:
    """认证服务测试"""
    
    @pytest.mark.asyncio
    async def test_authenticate_user_success(self):
        """测试用户认证成功"""
        # 创建模拟的数据库会话
        mock_session = AsyncMock(spec=AsyncSession)
        
        # 创建认证服务
        auth_service = AuthService(mock_session)
        
        # 模拟用户存在且密码正确
        mock_user = User()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.hashed_password = "hashed_password"  # 简单哈希，测试中会被mock
        mock_user.is_active = True
        
        # 模拟服务方法 - 完全绕过密码验证
        with patch.object(auth_service.user_repo, 'get_by_username', return_value=mock_user), \
             patch('app.services.auth_service.verify_password', return_value=True):
            
            user = await auth_service.authenticate("testuser", "password")
            
            # 验证返回了正确的用户
            assert user is not None
            assert user.username == "testuser"
            assert user.id == 1
    
    @pytest.mark.asyncio
    async def test_authenticate_user_wrong_password(self):
        """测试用户密码错误"""
        # 创建模拟的数据库会话
        mock_session = AsyncMock(spec=AsyncSession)
        
        # 创建认证服务
        auth_service = AuthService(mock_session)
        
        # 模拟用户存在但密码错误
        mock_user = User()
        mock_user.username = "testuser"
        mock_user.hashed_password = "hashed_password"  # 简单哈希，测试中会被mock
        
        # 模拟服务方法 - 完全绕过密码验证
        with patch.object(auth_service.user_repo, 'get_by_username', return_value=mock_user), \
             patch('app.services.auth_service.verify_password', return_value=False):
            
            user = await auth_service.authenticate("testuser", "wrong_password")
            
            # 验证返回None
            assert user is None
    
    @pytest.mark.asyncio
    async def test_authenticate_nonexistent_user(self):
        """测试认证不存在的用户"""
        # 创建模拟的数据库会话
        mock_session = AsyncMock(spec=AsyncSession)
        
        # 创建认证服务
        auth_service = AuthService(mock_session)
        
        # 模拟用户不存在
        with patch.object(auth_service.user_repo, 'get_by_username', return_value=None):
            user = await auth_service.authenticate("nonexistent", "password")
            
            # 验证返回None
            assert user is None
    
    @pytest.mark.asyncio
    async def test_create_user(self):
        """测试创建用户"""
        # 创建模拟的数据库会话
        mock_session = AsyncMock(spec=AsyncSession)
        
        # 创建认证服务
        auth_service = AuthService(mock_session)
        
        # 模拟用户创建
        mock_created_user = User()
        mock_created_user.id = 1
        mock_created_user.username = "newuser"
        mock_created_user.email = "new@example.com"
        mock_created_user.is_active = True
        
        # 模拟服务方法
        with patch.object(auth_service.user_repo, 'get_by_username', return_value=None), \
             patch.object(auth_service.user_repo, 'get_by_email', return_value=None), \
             patch.object(auth_service.user_repo, 'create', return_value=mock_created_user), \
             patch('app.core.security.get_password_hash', return_value="hashed_password"):
            
            user_data = UserCreate(
                username="newuser",
                email="new@example.com",
                password="password123"
            )
            
            user = await auth_service.create_user(user_data)
            
            # 验证用户创建
            assert user is not None
            assert user.username == "newuser"
            assert user.email == "new@example.com"
            
            # 验证调用正确的参数
            auth_service.user_repo.create.assert_called_once()


class TestRBACService:
    """RBAC服务测试"""
    
    @pytest.mark.asyncio
    async def test_check_user_permission(self):
        """测试用户权限检查"""
        from app.repositories.rbac_repo import RBACRepository
        from app.services.rbac_service import RBACService
        from app.models.user import User
        from app.models.role import Role
        from app.models.permission import Permission
        
        # 创建模拟的数据库会话
        mock_session = AsyncMock(spec=AsyncSession)
        
        # 创建RBAC服务
        rbac_service = RBACService(mock_session)
        
        # 创建模拟用户（无权限）
        mock_user = User()
        mock_user.id = 1
        mock_user.is_superuser = False
        mock_user.roles = []
        
        # 模拟服务方法
        with patch.object(rbac_service.rbac_repo, 'get_user_with_roles', return_value=mock_user):
            # 测试无权限用户
            has_permission = await rbac_service.check_permission(
                user_id=1,
                resource="user",
                action="read"
            )
            
            # 验证结果
            assert has_permission is False
        
        # 测试超级用户
        mock_user.is_superuser = True
        with patch.object(rbac_service.rbac_repo, 'get_user_with_roles', return_value=mock_user):
            has_permission = await rbac_service.check_permission(
                user_id=1,
                resource="user",
                action="read"
            )
            
            # 验证结果
            assert has_permission is True
    
    @pytest.mark.asyncio
    async def test_assign_role_to_user(self):
        """测试为用户分配角色"""
        from app.repositories.rbac_repo import RBACRepository
        from app.services.rbac_service import RBACService
        from app.models.user import User
        from app.models.role import Role
        
        # 创建模拟的数据库会话
        mock_session = AsyncMock(spec=AsyncSession)
        
        # 创建RBAC服务
        rbac_service = RBACService(mock_session)
        
        # 创建模拟用户和角色
        mock_user = User()
        mock_user.roles = []
        
        mock_role = Role()
        mock_role.id = 1
        mock_role.name = "test_role"
        
        # 模拟服务方法
        with patch.object(rbac_service.rbac_repo, 'get_user_by_id', return_value=mock_user), \
             patch.object(rbac_service.rbac_repo, 'get_role_by_id', return_value=mock_role), \
             patch.object(mock_session, 'commit'):
            
            # 测试角色分配
            result = await rbac_service.assign_role_to_user(
                user_id=1,
                role_id=1
            )
            
            # 验证结果
            assert result is True
            assert mock_role in mock_user.roles
            
            # 验证commit被调用
            mock_session.commit.assert_called_once()
        
        # 测试不存在的用户
        with patch.object(rbac_service.rbac_repo, 'get_user_by_id', return_value=None):
            result = await rbac_service.assign_role_to_user(
                user_id=999,
                role_id=1
            )
            
            # 验证结果
            assert result is False