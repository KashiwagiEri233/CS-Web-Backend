# 数据库与事务

## 概述

`app/database.py` 提供 PostgreSQL 异步引擎、会话工厂、请求/非请求会话入口，以及
Alembic 启动校验。全环境 schema 唯一来源是 Alembic，禁止 `create_all`。

## 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `get_db` | `async generator[AsyncSession]` | FastAPI 请求依赖 |
| `get_session` | `async context manager[AsyncSession]` | worker、脚本和后台任务 |
| `ensure_database_exists` | `await ensure_database_exists() -> bool` | 可选创建目标库 |
| `startup_database` | lifecycle startup task | 迁移/版本校验和连通性探测 |

## 配置

数据库 URL 可由 `DATABASE_URL` 提供，也可由 host/port/name/user/password 组装。
连接池由 `DB_POOL_*` 控制；`DB_AUTO_CREATE_DATABASE` 控制建库，
`DB_AUTO_MIGRATE` 控制自动 upgrade，否则只校验数据库 revision 与代码 head 一致。

## 事务与不变量

- Repository 只 `flush`，Service 显式 `commit`。
- 请求外会话发生异常时自动 rollback，但不会自动 commit。
- 组合业务调用 Service 时使用 `commit=False`，由最外层事务一次提交。
- 多 worker 自动迁移和 RBAC seed 分别使用 PostgreSQL advisory lock。
- 模型时间列统一 `DateTime(timezone=True)`。

## 测试

- CI 执行 `upgrade head → downgrade base → upgrade head`。
- `tests/integration/test_http_postgres_e2e.py` 覆盖完整 HTTP 到 PostgreSQL 链路。
- `tests/integration/test_auth_token_lifecycle.py` 和 `test_rbac_db.py` 覆盖关键事务。

## 扩展指引

修改模型后新增增量迁移，检查单一 head；不得修改历史迁移或在测试中调用
`Base.metadata.create_all`。

