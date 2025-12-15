import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_user_management_workflow(client: AsyncClient, superuser_token_headers):
    """测试完整的用户管理工作流"""
    # 创建用户
    user_data = {
        "username": "workflow_user",
        "email": "workflow@example.com",
        "password": "test123",  # 使用较短的密码
        "full_name": "工作流测试用户",
        "is_active": True
    }
    
    create_response = await client.post(
        "/api/v1/users/",
        json=user_data,
        headers=superuser_token_headers
    )
    
    assert create_response.status_code == 200
    created_user = create_response.json()
    print(f"Created user response: {created_user}")
    user_id = created_user["id"]
    print(f"User ID: {user_id}")
    
    # 获取用户列表
    list_response = await client.get(
        "/api/v1/users/",
        headers=superuser_token_headers
    )
    
    assert list_response.status_code == 200
    users = list_response.json()
    print(f"Users list: {users}")
    assert any(user["id"] == user_id for user in users)
    
    # 获取单个用户
    get_response = await client.get(
        f"/api/v1/users/{user_id}",
        headers=superuser_token_headers
    )
    
    assert get_response.status_code == 200
    user_detail = get_response.json()
    assert user_detail["username"] == "workflow_user"
    assert user_detail["email"] == "workflow@example.com"
    
    # 更新用户
    update_data = {
        "email": "updated@example.com",
        "full_name": "更新后的用户名",
        "is_active": False
    }
    
    update_response = await client.put(
        f"/api/v1/users/{user_id}",
        json=update_data,
        headers=superuser_token_headers
    )
    
    assert update_response.status_code == 200
    updated_user = update_response.json()
    assert updated_user["email"] == "updated@example.com"
    assert updated_user["full_name"] == "更新后的用户名"
    assert updated_user["is_active"] is False
    
    # 删除用户
    delete_response = await client.post(
        f"/api/v1/users/{user_id}/delete",
        headers=superuser_token_headers
    )
    
    assert delete_response.status_code == 200
    
    # 验证用户已删除
    get_deleted_response = await client.get(
        f"/api/v1/users/{user_id}",
        headers=superuser_token_headers
    )
    
    assert get_deleted_response.status_code == 404


@pytest.mark.asyncio
async def test_rbac_permission_workflow(client: AsyncClient, superuser_token_headers, normal_user_token_headers):
    """测试完整的RBAC权限工作流"""
    # 创建权限
    permission_data = {
        "name": "resource_create",
        "resource": "resource",
        "action": "create",
        "description": "创建资源权限"
    }
    
    permission_response = await client.post(
        "/api/v1/rbac/permissions",
        json=permission_data,
        headers=superuser_token_headers
    )
    
    assert permission_response.status_code == 200
    permission_id = permission_response.json()["id"]
    
    # 创建角色
    role_data = {
        "name": "resource_manager",
        "description": "资源管理员角色"
    }
    
    role_response = await client.post(
        "/api/v1/rbac/roles",
        json=role_data,
        headers=superuser_token_headers
    )
    
    assert role_response.status_code == 200
    role_id = role_response.json()["id"]
    
    # 为角色分配权限
    assign_response = await client.post(
        f"/api/v1/rbac/roles/{role_id}/permissions/{permission_id}",
        headers=superuser_token_headers
    )
    
    assert assign_response.status_code == 200
    
    # 创建用户
    user_data = {
        "username": "rbac_test_user",
        "email": "rbac@example.com",
        "password": "rbacpassword",
        "is_active": True
    }
    
    user_response = await client.post(
        "/api/v1/auth/register",
        params=user_data
    )
    
    assert user_response.status_code == 200
    user_id = user_response.json()["id"]
    
    # 为用户分配角色
    assign_role_response = await client.post(
        f"/api/v1/rbac/users/{user_id}/roles/{role_id}",
        headers=superuser_token_headers
    )
    
    assert assign_role_response.status_code == 200
    
    # 检查用户权限
    check_response = await client.post(
        f"/api/v1/rbac/users/{user_id}/check-permission",
        json={"resource": "resource", "action": "create"},
        headers=superuser_token_headers
    )
    
    assert check_response.status_code == 200
    assert check_response.json()["has_permission"] is True
    
    # 检查用户没有的权限
    check_no_perm_response = await client.post(
        f"/api/v1/rbac/users/{user_id}/check-permission",
        json={"resource": "resource", "action": "delete"},
        headers=superuser_token_headers
    )
    
    assert check_no_perm_response.status_code == 200
    assert check_no_perm_response.json()["has_permission"] is False
    
    # 从用户撤销角色
    revoke_role_response = await client.post(
        f"/api/v1/rbac/users/{user_id}/roles/{role_id}/revoke",
        headers=superuser_token_headers
    )
    
    # 检查用户是否失去权限
    check_revoked_response = await client.post(
        f"/api/v1/rbac/users/{user_id}/check-permission",
        json={"resource": "resource", "action": "create"},
        headers=superuser_token_headers
    )
    
    assert check_revoked_response.status_code == 200
    assert check_revoked_response.json()["has_permission"] is False


@pytest.mark.asyncio
async def test_admin_dashboard_access(client: AsyncClient, superuser_token_headers, normal_user_token_headers):
    """测试管理后台访问控制"""
    # 超级用户可以访问管理后台
    admin_response = await client.get(
        "/admin/",
        headers=superuser_token_headers
    )
    
    assert admin_response.status_code == 200
    
    # 普通用户无法访问管理后台
    normal_user_response = await client.get(
        "/admin/",
        headers=normal_user_token_headers
    )
    
    assert normal_user_response.status_code == 403
    
    # 未登录用户无法访问管理后台
    unauth_response = await client.get("/admin/")
    
    assert unauth_response.status_code == 401


@pytest.mark.asyncio
async def test_api_endpoint_protection(client: AsyncClient, superuser_token_headers, normal_user_token_headers):
    """测试API端点保护"""
    # 超级用户可以创建用户
    create_user_response = await client.post(
        "/api/v1/users/",
        json={
            "username": "protected_test_user",
            "email": "protected@example.com",
            "password": "protectedpassword",
            "is_active": True
        },
        headers=superuser_token_headers
    )
    
    assert create_user_response.status_code == 200
    
    # 普通用户无法创建用户
    normal_create_response = await client.post(
        "/api/v1/users/",
        json={
            "username": "normal_protected_test_user",
            "email": "normal_protected@example.com",
            "password": "normal_protectedpassword",
            "is_active": True
        },
        headers=normal_user_token_headers
    )
    
    assert normal_create_response.status_code == 403
    
    # 未登录用户无法创建用户
    unauth_create_response = await client.post(
        "/api/v1/users/",
        json={
            "username": "unauth_protected_test_user",
            "email": "unauth_protected@example.com",
            "password": "unauth_protectedpassword",
            "is_active": True
        }
    )
    
    assert unauth_create_response.status_code == 401