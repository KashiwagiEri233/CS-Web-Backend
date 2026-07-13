# 审计日志（Audit）

## 概述

记录敏感管理操作（谁、何时、对什么资源做了什么），并提供只读查询。  
普通辅助写入可用 **best-effort** 独立会话；用户、角色、权限等敏感写操作使用
共享请求会话并严格提交，使业务变更与审计记录处于同一事务。查询走请求级
`AsyncSession`。

代码：`app/api/v1/audit.py`、`app/services/audit_service.py`、`app/models/audit_log.py`、`app/schemas/audit.py`。  
挂载前缀：`/api/v1/audit`，tag `审计日志`。

## 接口

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/logs` | `system:logs` | 分页列表 → `PaginatedResponse[AuditLogItem]` |
| GET | `/logs/{log_id}` | `system:logs` | 详情 → `AuditLogItem` |

查询参数（列表）：`skip` / `limit` / `action` / `resource_type` / `resource_id` / `actor_id` / `start_date` / `end_date`。  
schema 见 `app/schemas/audit.py`。

## 当前写入点

| action | 触发 |
|---|---|
| `user.create` | `POST /users`、`POST /auth/register` |
| `user.update` | `PUT /users/{id}` |
| `user.delete` | `DELETE /users/{id}` |
| `role.create/update/delete` | RBAC 角色写操作 |
| `permission.create/update/delete` | RBAC 权限写操作 |
| `user.grant_role` / `user.revoke_role` | 用户↔角色 |
| `role.grant_permission` / `role.revoke_permission` | 角色↔权限 |

## 配置 / 依赖

- 表：`audit_logs`（Alembic 迁移 `b8d4f02c3e15`）
- 权限种子：`system:logs`（见 `rbac_seed_data`）
- Service 注入：`Depends(get_audit_service)`

## 不变量

- 敏感管理写操作统一调用 `record_atomic()`：它固定使用共享会话、严格失败和一次提交，
  审计失败会回滚业务事务；路由不得自行组合三个布尔开关。
- 非关键辅助审计可保留默认 best-effort 策略，失败只打 warning。
- 查询需 `system:logs`；超级用户旁路 `require_permission`。

## 测试

- `tests/api/v1/test_audit.py`
