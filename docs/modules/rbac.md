# RBAC（角色 / 权限）

## 概述

角色、权限 CRUD，用户↔角色 / 角色↔权限分配，以及权限查询。  
管理端点用 **`require_permission`**；Service 经 **`Depends(get_rbac_service)`** 注入。  
写操作写审计（见 [audit.md](audit.md)）。

代码：`app/api/v1/rbac/`、`app/services/rbac_service.py`、`app/middleware/rbac.py`。  
前缀：`/api/v1/rbac`。

## 接口

### 角色
| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/roles` | `role:list` | 分页 `PaginatedResponse[Role]` |
| POST | `/roles` | `role:create` | 创建 + 审计 |
| GET | `/roles/{role_id}` | `role:read` | 详情 |
| PUT | `/roles/{role_id}` | `role:update` | 更新 + 审计 |
| DELETE | `/roles/{role_id}` | `role:delete` | 删除 + 审计 |

### 权限
| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/permissions` | `permission:list` | 分页 |
| POST | `/permissions` | `permission:create` | 创建 + 审计 |
| GET | `/permissions/{permission_id}` | `permission:read` | 详情 |
| PUT | `/permissions/{permission_id}` | `permission:update` | 更新 + 审计 |
| DELETE | `/permissions/{permission_id}` | `permission:delete` | 删除 + 审计 |

### 分配与查询
| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST/DELETE | `/users/{uid}/roles/{rid}` | `user:manage_roles` | 赋/撤角色 + 审计 |
| POST/DELETE | `/roles/{rid}/permissions/{pid}` | `role:manage_permissions` | 赋/撤权限 + 审计 |
| POST | `/users/{uid}/check-permission` | 活跃用户（本人/超管） | 校验 |
| GET | `/me/permissions` · `/me/roles` | 活跃用户 | 当前授权 |
| GET | `/users/{uid}/permissions` · `/roles` | `user:read` | 指定用户 |

schema：`app/schemas/rbac.py`。

## 缓存

用户权限缓存键 `rbac:user_perms:{user_id}`，TTL 60s；grant/revoke 与角色/权限 CRUD 会失效。
缓存只用于权限展示/查询；实际授权依赖每次直接查询数据库，避免多实例缓存失效延迟扩大权限窗口。
停用角色不会授予角色身份或任何权限。

## 测试

`tests/api/v1/test_rbac.py`、`tests/services/test_rbac_service.py`、`tests/middleware/test_rbac_permissions.py`。
