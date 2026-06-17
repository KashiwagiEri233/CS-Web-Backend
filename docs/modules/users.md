# 用户管理（Users）

## 概述

用户实体的 CRUD 与"我"的自助维护。管理类操作（列表/查看他人/创建/改他人/删除）限**超级用户**；
"我"相关操作（看/改自己）限**当前活跃用户**。负责用户资源的增删改查，**不负责**认证流程
（见 [auth.md](auth.md)）与角色权限分配（见 [rbac.md](rbac.md)）。

代码：`app/api/v1/users.py`、`app/repositories/`（user repo）、模型 `app/models/`。
挂载前缀：`/api/v1/users`，tag `用户管理`。

## 接口

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | 超级用户 | 用户列表 → `List[UserResponse]` |
| GET | `/me` | 当前活跃用户 | 当前用户 → `UserResponse` |
| GET | `/{user_id}` | 超级用户 | 按 ID 查用户 → `UserResponse` |
| POST | `/` | 超级用户 | 创建用户 → `UserResponse` |
| PUT | `/{user_id}` | 超级用户 | 更新指定用户 → `UserResponse` |
| PUT | `/me` | 当前活跃用户 | 更新自己（邮箱唯一性校验、可改密码/姓名） |
| DELETE | `/{user_id}` | 超级用户 | 删除用户（**禁止删除自己**） |

入/出参 schema 见 `app/schemas/`（`UserResponse`、用户创建/更新 schema）。

## 配置

无专属配置；默认管理员见 `ADMIN_USERNAME` / `ADMIN_EMAIL` / `ADMIN_PASSWORD`（仅首次初始化创建）。

## 依赖与协作

- 数据访问：user repository（构造收 `AsyncSession`）。
- 鉴权依赖：`get_current_active_user` / `get_current_superuser`（`app/dependencies.py`）。
- 密码哈希：`app/core/security.py` 的 `get_password_hash`（改密时）。

## 不变量

- `DELETE /{user_id}` 禁止删除当前登录用户自身（防止管理员误删自己锁死系统）。
- `PUT /me` 改邮箱时做唯一性校验，冲突抛 `ConflictException`。

## 测试

用户 CRUD 主要经集成路径覆盖；权限边界见 `tests/middleware/test_rbac_permissions.py`。
新增用户相关逻辑时在 `tests/` 对应子包补单测。

## 扩展指引

加用户相关端点走 `app/api/v1/users.py`；区分"管理他人"（superuser）与"操作自己"（active user）
两类鉴权，不要混用。字段变更同步 `app/schemas/` 与 `app/models/`（模型改动记得在
`app/models/__init__.py` 登记，见 `AGENTS.md`）。
