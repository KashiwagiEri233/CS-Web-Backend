import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_get_roles(client: AsyncClient, superuser_token_headers):
    """测试获取角色列表"""
    response = await client.get(
        "/api/v1/rbac/roles",
        headers=superuser_token_headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_permissions(client: AsyncClient, superuser_token_headers):
    """测试获取权限列表"""
    response = await client.get(
        "/api/v1/rbac/permissions",
        headers=superuser_token_headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_create_role(client: AsyncClient, superuser_token_headers):
    """测试创建角色"""
    role_data = {
        "name": "test_role",
        "description": "测试角色",
        "is_active": True
    }
    
    response = await client.post(
        "/api/v1/rbac/roles",
        json=role_data,
        headers=superuser_token_headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_role"
    assert data["description"] == "测试角色"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_permission(client: AsyncClient, superuser_token_headers):
    """测试创建权限"""
    permission_data = {
        "name": "test_permission",
        "resource": "test",
        "action": "read",
        "description": "测试权限"
    }
    
    response = await client.post(
        "/api/v1/rbac/permissions",
        json=permission_data,
        headers=superuser_token_headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_permission"
    assert data["resource"] == "test"
    assert data["action"] == "read"
    assert data["description"] == "测试权限"


@pytest.mark.asyncio
async def test_assign_permission_to_role(client: AsyncClient, superuser_token_headers):
    """测试为角色分配权限"""
    # 首先创建角色和权限
    role_response = await client.post(
        "/api/v1/rbac/roles",
        json={"name": "test_role_with_perm", "description": "带权限的测试角色"},
        headers=superuser_token_headers
    )
    role_id = role_response.json()["id"]
    
    permission_response = await client.post(
        "/api/v1/rbac/permissions",
        json={"name": "test_perm_for_role", "resource": "test", "action": "write"},
        headers=superuser_token_headers
    )
    permission_id = permission_response.json()["id"]
    
    # 为角色分配权限
    response = await client.post(
        f"/api/v1/rbac/roles/{role_id}/permissions/{permission_id}",
        headers=superuser_token_headers
    )
    
    assert response.status_code == 200
    
    # 验证角色拥有权限
    role_detail_response = await client.get(
        f"/api/v1/rbac/roles/{role_id}",
        headers=superuser_token_headers
    )
    assert role_detail_response.status_code == 200
    role_data = role_detail_response.json()
    assert len(role_data["permissions"]) == 1
    assert role_data["permissions"][0]["id"] == permission_id


@pytest.mark.asyncio
async def test_check_user_permission(client: AsyncClient, superuser_token_headers):
    """测试检查用户权限"""
    # 创建普通用户
    user_data = {
        "username": "permission_test_user",
        "email": "permission@example.com",
        "password": "testpassword",
        "is_active": True
    }
    
    register_response = await client.post(
        "/api/v1/auth/register",
        params=user_data
    )
    assert register_response.status_code == 200
    user_id = register_response.json()["id"]
    
    # 创建测试权限
    permission_response = await client.post(
        "/api/v1/rbac/permissions",
        json={"name": "user_test_permission", "resource": "user", "action": "read"},
        headers=superuser_token_headers
    )
    permission_id = permission_response.json()["id"]
    
    # 创建测试角色
    role_response = await client.post(
        "/api/v1/rbac/roles",
        json={"name": "user_test_role", "description": "用户测试角色"},
        headers=superuser_token_headers
    )
    role_id = role_response.json()["id"]
    
    # 为角色分配权限
    await client.post(
        f"/api/v1/rbac/roles/{role_id}/permissions/{permission_id}",
        headers=superuser_token_headers
    )
    
    # 为用户分配角色
    await client.post(
        f"/api/v1/rbac/users/{user_id}/roles/{role_id}",
        headers=superuser_token_headers
    )
    
    # 检查用户权限
    permission_check_response = await client.post(
        f"/api/v1/rbac/users/{user_id}/check-permission",
        json={"resource": "user", "action": "read"},
        headers=superuser_token_headers
    )
    
    assert permission_check_response.status_code == 200
    assert permission_check_response.json()["has_permission"] is True
    
    # 检查用户没有的权限
    no_permission_response = await client.post(
        f"/api/v1/rbac/users/{user_id}/check-permission",
        json={"resource": "user", "action": "delete"},
        headers=superuser_token_headers
    )
    
    assert no_permission_response.status_code == 200
    assert no_permission_response.json()["has_permission"] is False