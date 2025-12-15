import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.repositories.user_repo import UserRepository
from app.repositories.rbac_repo import RBACRepository
from app.models import User, Role, Permission


class TestUserRepository:
    """用户仓储测试"""
    
    @pytest.mark.asyncio
    async def test_get_by_username(self):
        """测试通过用户名获取用户"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = MagicMock(spec=User)
        mock_session.execute.return_value = mock_result
        
        repo = UserRepository(mock_session)
        user = await repo.get_by_username("testuser")
        
        # 验证查询执行
        mock_session.execute.assert_called_once()
        # 验证返回的用户
        assert user is not None
    
    @pytest.mark.asyncio
    async def test_get_by_email(self):
        """测试通过邮箱获取用户"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = MagicMock(spec=User)
        mock_session.execute.return_value = mock_result
        
        repo = UserRepository(mock_session)
        user = await repo.get_by_email("test@example.com")
        
        # 验证查询执行
        mock_session.execute.assert_called_once()
        # 验证返回的用户
        assert user is not None
    
    @pytest.mark.asyncio
    async def test_create_user(self):
        """测试创建用户"""
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.username = "newuser"
        
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        repo = UserRepository(mock_session)
        
        # 使用patch来模拟User构造函数
        with patch('app.repositories.user_repo.User', return_value=mock_user):
            result = await repo.create({
                "username": "newuser",
                "email": "test@example.com",
                "password": "hashed_password"
            })
        
        # 验证数据库操作
        mock_session.add.assert_called_once_with(mock_user)
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once_with(mock_user)
        
        # 验证返回的用户
        assert result.id == 1
        assert result.username == "newuser"
    
    @pytest.mark.asyncio
    async def test_get_user_with_roles(self):
        """测试获取用户及其角色"""
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.roles = []
        
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_result
        
        repo = UserRepository(mock_session)
        user = await repo.get_user_with_roles(1)
        
        # 验证查询执行
        mock_session.execute.assert_called_once()
        # 验证返回的用户
        assert user is not None
        assert user.id == 1


class TestRBACRepository:
    """RBAC仓储测试"""
    
    @pytest.mark.asyncio
    async def test_create_role(self):
        """测试创建角色"""
        mock_role = MagicMock(spec=Role)
        mock_role.id = 1
        mock_role.name = "test_role"
        
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        repo = RBACRepository(mock_session)
        
        with patch('app.repositories.rbac_repo.Role', return_value=mock_role):
            result = await repo.create_role({
                "name": "test_role",
                "description": "Test role description"
            })
        
        # 验证数据库操作
        mock_session.add.assert_called_once_with(mock_role)
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once_with(mock_role)
        
        # 验证返回的角色
        assert result.id == 1
        assert result.name == "test_role"
    
    @pytest.mark.asyncio
    async def test_create_permission(self):
        """测试创建权限"""
        mock_permission = MagicMock(spec=Permission)
        mock_permission.id = 1
        mock_permission.name = "test_permission"
        
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        repo = RBACRepository(mock_session)
        
        with patch('app.repositories.rbac_repo.Permission', return_value=mock_permission):
            result = await repo.create_permission({
                "name": "test_permission",
                "resource": "test",
                "action": "read"
            })
        
        # 验证数据库操作
        mock_session.add.assert_called_once_with(mock_permission)
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once_with(mock_permission)
        
        # 验证返回的权限
        assert result.id == 1
        assert result.name == "test_permission"
    
    @pytest.mark.asyncio
    async def test_assign_permission_to_role(self):
        """测试为角色分配权限"""
        mock_role = MagicMock(spec=Role)
        mock_role.id = 1
        mock_role.permissions = []
        
        mock_permission = MagicMock(spec=Permission)
        mock_permission.id = 2
        
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalars.return_value.first.return_value = mock_role
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        
        repo = RBACRepository(mock_session)
        
        # 模拟权限查询也成功
        def mock_execute_side_effect(query):
            mock_result = AsyncMock()
            if "Permission" in str(query):
                mock_result.scalar_one_or_none.return_value = mock_permission
            else:
                mock_result.scalars.return_value.first.return_value = mock_role
            return mock_result
        
        mock_session.execute.side_effect = mock_execute_side_effect
        
        result = await repo.assign_permission_to_role(
            role_id=1,
            permission_id=2
        )
        
        # 验证结果
        assert result is True
        mock_session.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_check_user_permission(self):
        """测试检查用户权限"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = AsyncMock()
        mock_result.scalar.return_value = True  # 模拟用户有权限
        mock_session.execute.return_value = mock_result
        
        repo = RBACRepository(mock_session)
        
        has_permission = await repo.check_user_permission(
            user_id=1,
            resource="user",
            action="read"
        )
        
        # 验证查询执行
        mock_session.execute.assert_called_once()
        # 验证返回的权限检查结果
        assert has_permission is True