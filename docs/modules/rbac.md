# RBAC（角色 / 权限）

## 概述

基于角色的访问控制：管理角色、权限，及"用户↔角色""角色↔权限"的分配，并提供权限校验查询。
所有管理类端点限**超级用户**；权限查询（`check-permission`）限当前活跃用户且只能查自己（超级用户可查任何人）。
负责授权数据的维护与查询，**不负责**身份认证（见 [auth.md](auth.md)）。

代码：`app/api/v1/rbac.py`、`app/services/rbac_service.py`、初始化 `app/services/rbac_init.py`、
权限校验依赖 `app/middleware/rbac.py`。挂载前缀：`/api/v1/rbac`，tag `RBAC权限管理`。

## 接口

### 角色
| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/roles` | 超级用户 | 角色列表 → `List[Role]` |
| POST | `/roles` | 超级用户 | 创建角色 → `Role` |
| GET | `/roles/{role_id}` | 超级用户 | 角色详情 → `Role` |
| PUT | `/roles/{role_id}` | 超级用户 | 更新角色 → `Role` |
| DELETE | `/roles/{role_id}` | 超级用户 | 删除角色 |

### 权限
| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/permissions` | 超级用户 | 权限列表 → `List[Permission]` |
| POST | `/permissions` | 超级用户 | 创建权限 → `Permission` |
| GET | `/permissions/{permission_id}` | 超级用户 | 权限详情 → `Permission` |
| PUT | `/permissions/{permission_id}` | 超级用户 | 更新权限 → `Permission` |
| DELETE | `/permissions/{permission_id}` | 超级用户 | 删除权限 |

### 分配与校验
| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/users/{user_id}/roles/{role_id}` | 超级用户 | 给用户赋角色 |
| DELETE | `/users/{user_id}/roles/{role_id}` | 超级用户 | 移除用户角色 |
| POST | `/roles/{role_id}/permissions/{permission_id}` | 超级用户 | 给角色赋权限 |
| DELETE | `/roles/{role_id}/permissions/{permission_id}` | 超级用户 | 移除角色权限 |
| POST | `/users/{user_id}/check-permission` | 活跃用户（自己 / 超级用户查任意） | 校验某用户是否具备权限 → `UserPermissionResult` |

入/出参 schema 见 `app/schemas/`（`Role`、`Permission`、`UserPermissionResult` 等）。

## 配置

无专属配置。RBAC 基础数据（默认角色/权限/管理员）在应用启动 lifespan 中由
`app/services/rbac_init.py` 幂等初始化。

## 依赖与协作

- 业务逻辑：`rbac_service.py`（构造收 `db`）。
- **权限校验依赖**：`app/middleware/rbac.py` 提供 `require_permission` / `require_role` /
  `require_superuser`——用于**其它业务路由**做细粒度授权（用 `Depends`，不要用装饰器，见 `AGENTS.md`）。

> 现状提示：本模块的管理端点目前统一用 `get_current_superuser` 把关，**未**用 `require_permission`
> 的细粒度权限码。`require_permission` 是给业务路由按"资源:动作"授权用的能力。

## 不变量

- RBAC 初始化必须幂等（重复启动不重复建）——见 `rbac_init.py`。
- 权限校验统一走 `Depends`，禁止散落的手写 if 判断（自助查询端点的"自己/超级用户"判断除外）。

## 测试

`tests/middleware/test_rbac_permissions.py`（权限校验依赖）、`tests/integration/test_rbac_db.py`
（需真实库的 RBAC 流程，默认 skip）。

## 扩展指引

加授权能力：业务逻辑进 `rbac_service.py`；要给某业务路由加权限门禁，在该路由用
`Depends(require_permission("<资源>", "<动作>"))`，不要在 RBAC 模块里堆业务判断。
