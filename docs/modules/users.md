# 用户管理（Users）

## 概述

用户 CRUD 与自助资料。管理操作 `require_permission`；Service 经 `Depends(get_user_service)`。  
软删除（`deleted_at`）；改密与撤 refresh **同一事务**。

代码：`app/api/v1/users.py`、`app/services/user_service.py`。  
前缀：`/api/v1/users`。

## 接口

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | `user:list` | 分页列表（不含已软删） |
| GET | `/me` | 活跃用户 | 当前用户 |
| GET | `/{user_id}` | `user:read` | 详情 |
| POST | `/` | `user:create` | 创建 + 审计 |
| PUT | `/{user_id}` | `user:update` | 更新；改密同事务撤 refresh + 审计 |
| PUT | `/me` | 活跃用户 | 自助（不可改 is_active） |
| DELETE | `/{user_id}` | `user:delete` | 软删 + 撤 refresh + 审计（禁自删） |

## 安全

- 改密：`password_changed_at` + 微秒精度 JWT `pwd_at`；同事务 `revoke_all_for_user`。
- 密码按 UTF-8 编码后最多 72 字节，避免 bcrypt 静默截断。
- 软删：释放 username/email 唯一键（截断拼接后缀）。

## 测试

`tests/api/v1/test_users.py`、`tests/services/test_user_service.py`。
