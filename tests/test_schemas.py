import pytest
from pydantic import ValidationError

from app.schemas.auth import Token, TokenData, UserCreate, UserResponse
from app.schemas.user import UserUpdate
from app.schemas.rbac import RoleCreate, Role, PermissionCreate, Permission


class TestAuthSchemas:
    """认证模式测试"""
    
    def test_token_schema(self):
        """测试令牌模式"""
        token_data = {
            "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
            "token_type": "bearer"
        }
        
        token = Token(**token_data)
        
        assert token.access_token == token_data["access_token"]
        assert token.token_type == "bearer"
    
    def test_token_data_schema(self):
        """测试令牌数据模式"""
        token_data = {
            "username": "testuser",
            "user_id": 1
        }
        
        data = TokenData(**token_data)
        
        assert data.username == "testuser"
        assert data.user_id == 1
    
    def test_user_create_schema(self):
        """测试用户创建模式"""
        user_data = {
            "username": "newuser",
            "email": "new@example.com",
            "password": "password123",
            "full_name": "New User"
        }
        
        user = UserCreate(**user_data)
        
        assert user.username == "newuser"
        assert user.email == "new@example.com"
        assert user.password == "password123"
        assert user.full_name == "New User"
    
    def test_user_create_invalid_email(self):
        """测试无效邮箱的用户创建"""
        user_data = {
            "username": "newuser",
            "email": "invalid-email",
            "password": "password123"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(**user_data)
        
        # 验证邮箱验证错误
        assert "value is not a valid email address" in str(exc_info.value)
    
    def test_user_create_short_password(self):
        """测试密码过短的用户创建"""
        user_data = {
            "username": "newuser",
            "email": "test@example.com",
            "password": "123"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(**user_data)
        
        # 验证密码长度错误
        assert "密码长度至少为6个字符" in str(exc_info.value)


class TestUserSchemas:
    """用户模式测试"""
    
    def test_user_update_schema(self):
        """测试用户更新模式"""
        update_data = {
            "email": "updated@example.com",
            "full_name": "Updated Name",
            "is_active": False
        }
        
        user_update = UserUpdate(**update_data)
        
        assert user_update.email == "updated@example.com"
        assert user_update.full_name == "Updated Name"
        assert user_update.is_active is False
    
    def test_user_update_partial(self):
        """测试部分用户更新"""
        update_data = {
            "email": "partial@example.com"
        }
        
        user_update = UserUpdate(**update_data)
        
        assert user_update.email == "partial@example.com"
        assert user_update.full_name is None
        assert user_update.is_active is None


class TestRBACSchemas:
    """RBAC模式测试"""
    
    def test_role_create_schema(self):
        """测试角色创建模式"""
        role_data = {
            "name": "test_role",
            "description": "Test role description",
            "is_active": True
        }
        
        role = RoleCreate(**role_data)
        
        assert role.name == "test_role"
        assert role.description == "Test role description"
        assert role.is_active is True
    
    def test_role_response_schema(self):
        """测试角色响应模式"""
        role_data = {
            "id": 1,
            "name": "test_role",
            "description": "Test role description",
            "is_active": True,
            "permissions": []
        }
        
        role = Role(**role_data)
        
        assert role.id == 1
        assert role.name == "test_role"
        assert role.description == "Test role description"
        assert role.is_active is True
        assert role.permissions == []
    
    def test_permission_create_schema(self):
        """测试权限创建模式"""
        permission_data = {
            "name": "test_permission",
            "resource": "user",
            "action": "read",
            "description": "Read user permission"
        }
        
        permission = PermissionCreate(**permission_data)
        
        assert permission.name == "test_permission"
        assert permission.resource == "user"
        assert permission.action == "read"
        assert permission.description == "Read user permission"
    
    def test_permission_response_schema(self):
        """测试权限响应模式"""
        permission_data = {
            "id": 1,
            "name": "test_permission",
            "resource": "user",
            "action": "read",
            "description": "Read user permission"
        }
        
        permission = Permission(**permission_data)
        
        assert permission.id == 1
        assert permission.name == "test_permission"
        assert permission.resource == "user"
        assert permission.action == "read"
        assert permission.description == "Read user permission"
    
    def test_permission_create_invalid_action(self):
        """测试无效动作的权限创建"""
        permission_data = {
            "name": "test_permission",
            "resource": "user",
            "action": "invalid_action",
            "description": "Invalid action permission"
        }
        
        # 如果有枚举限制，这里会验证
        # 目前没有限制，所以应该成功
        permission = PermissionCreate(**permission_data)
        assert permission.action == "invalid_action"