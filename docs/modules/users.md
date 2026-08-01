# 用户管理（Users）

## 概述

用户 CRUD、自助资料与公开主页（Phase 1 迁移）。管理操作 `require_permission`；Service 经 `Depends(get_user_service)`。  
软删除（`deleted_at`）；改密与撤 refresh **同一事务**。

代码：`app/api/v1/users.py`、`app/api/v1/profile.py`、`app/services/user_service.py`。  
前缀：`/api/v1/users`、`/api/v1/profile`、`/api/v1/avatars`。

## 接口

### 用户管理

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/users` | `user:list` | 分页列表（不含已软删） |
| GET | `/users/me` | 活跃用户 | 当前用户 |
| GET | `/users/{user_id}` | `user:read` | 详情 |
| POST | `/users` | `user:create` | 创建 + 审计 |
| PUT | `/users/{user_id}` | `user:update` | 更新；改密同事务撤 refresh + 审计 |
| PUT | `/users/me` | 活跃用户 | 自助（不可改 is_active；改密需 `old_password`） |
| DELETE | `/users/{user_id}` | `user:delete` | 软删 + 撤 refresh + 审计（禁自删） |

### 个人资料（前端主路径）

| Method | Path | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/profile` | 活跃用户 | 完整资料 + 活动参与记录（`ProfileResponse`） |
| PUT | `/profile` | 活跃用户 | 更新 displayName/bio/githubUrl/websiteUrl/techTags（`UserOut`） |
| POST | `/profile/password` | 活跃用户 | 改密（旧密码 + 历史复用检测 + 全端登出） |
| POST | `/profile/avatar/preset` | 活跃用户 | 预设头像（preset_id 1-6） |
| POST | `/profile/avatar/upload` | 活跃用户 | 上传头像（≤2MB，JPEG/PNG/WebP/GIF，魔数校验） |
| GET | `/avatars/{filename}` | 公开 | 头像静态服务（文件名严格校验防路径遍历） |
| GET | `/users/{user_id}` | 公开 | 用户公开主页 + 论坛/考试统计 |

schema 见 `app/schemas/profile.py`。字段限制与前端一致：displayName ≤32、bio ≤200、URL ≤500（仅 http/https）。

## 安全

- 改密：`password_changed_at` + 微秒精度 JWT `pwd_at`；同事务 `revoke_all_for_user`。
- 自助改密必须校验旧密码（`old_password`），防 access token 泄露被直接接管；管理端 `PUT /{user_id}` 重置不需要。
- 密码按 UTF-8 编码后最多 72 字节，避免 bcrypt 静默截断。
- 软删：释放 username/email 唯一键（截断拼接后缀）。
- 头像：四重校验（大小 / MIME 白名单 / 扩展名白名单 / 文件头魔数）；文件名服务端生成（`user<id>-<ts><ext>`），不使用原始文件名。
- 公开主页仅返回已激活未软删用户。

## 测试

`tests/api/v1/test_users.py`、`tests/services/test_user_service.py`、`tests/integration/test_auth_phase1.py`（资料/会话流）。
