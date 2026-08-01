# MIGRATION_VERIFICATION — 迁移验证指南（Linux / 有 PostgreSQL 环境）

> 执行者：Linux 环境的 agent（或任何具备 PostgreSQL 的 CI/开发机）
> 目的：验证 `d1e2f3a4b5c6_add_cs_business_tables.py`（Phase 0 数据层基线，离线手写）
> 与 `f6a7b8c9d0e1_add_refresh_tokens_device_info.py`（Phase 1 会话字段）是否与
> SQLAlchemy 模型元数据一致、能否正常升级/回滚；并跑通 Phase 1 认证全流程测试。
> 生成背景：迁移文件生成时开发机无 PostgreSQL 实例，无法 autogenerate，因此手写并需本验证。

---

## 一、预期结果摘要

| 检查项 | 预期 |
|---|---|
| `alembic heads` | 单一 head：`f6a7b8c9d0e1` |
| `alembic upgrade head` | 成功；42 张表建成（框架 8 + 业务 34，含 two_factor_auth） |
| `alembic check` | 无 drift（模型 ↔ 数据库一致） |
| `alembic downgrade -1 && upgrade head` | 往返成功 |
| Phase 1 集成测试 | `tests/integration/test_auth_phase1.py` 全绿（注册/2FA/懒升级/会话/重置流） |
| pytest | 全绿（除标记 integration 且无 Redis 时跳过的用例） |

---

## 二、准备环境

```bash
# 1. 启动 PostgreSQL（以下任一方式）
# 方式 A：Docker
docker run -d --name pg-domefff -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=<你的密码> \
  -e POSTGRES_DB=domefff -p 5432:5432 postgres:16
# 方式 B：系统包
sudo apt install postgresql
sudo -u postgres psql -c "CREATE USER postgres SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE domefff OWNER postgres;"

# 2. 配置环境
cd CS-Web-Backend
cp .env.development .env          # 或 .env.local
# 修改 .env：DATABASE_PASSWORD=<你的密码>、SECRET_KEY=<>=32 字节随机串、ADMIN_PASSWORD

# 3. 安装依赖
uv sync                            # 或 pip install --require-hashes -r requirements.lock
```

> 测试库另需：库名必须含 `test`（见 `tests/conftest.py` 校验），如
> `CREATE DATABASE domefff_test OWNER postgres;`

---

## 三、验证步骤

### 1. 迁移链完整性

```bash
uv run alembic heads          # 必须只有一行：d1e2f3a4b5c6 (head)
uv run alembic history | head -12
```

### 2. 升级到 head

```bash
uv run alembic upgrade head
```

预期成功。若报错，先看是否旧库残留：`alembic stamp head`（无版本表时）或
drop 库重建。

### 3. 模型 ↔ 数据库 drift 检查（关键）

```bash
uv run alembic check
```

- 输出 `No new upgrade operations detected` → 一致 ✅
- 输出差异 → **不要直接改模型**，把差异贴回迁移文件维护者：
  迁移文件与模型元数据不一致，需要修 `d1e2f3a4b5c6` / `f6a7b8c9d0e1` 的 upgrade/downgrade。

备用比对法（会生成临时 revision，验证后删除）：

```bash
uv run alembic revision --autogenerate -m "verify_drift"
# 打开生成的迁移文件：upgrade() 应为空或仅注释；若非空即 drift
uv run alembic downgrade -1   # 撤销该空迁移
rm alembic/versions/<新文件>   # 删除临时文件
```

### 3b. Phase 1 集成测试（认证全流程）

```bash
# 需要 domefff_test 测试库（库名含 test，见 conftest 校验）+ .env.test 的
# TOTP_ENCRYPTION_KEY/PASSWORD_RESET_DEFAULT（模板已含）
uv run python -m pytest tests/integration/test_auth_phase1.py -v --no-cov
```

覆盖：注册→登录→改密、2FA 全流程（setup/confirm/登录二次验证/备用码一次性）、
scrypt 懒升级、登录历史、设备列表/远程登出、忘记密码→批准→默认密码登录、验证码一次性。

### 3b2. Phase 2 集成测试（公告/通知/入社/管理员用户）

```bash
uv run python -m pytest tests/integration/test_phase2_modules.py -v --no-cov
```

覆盖：公告生命周期（生效/过期/角色定向/CRUD）、通知列表/已读/广播/群发记录聚合、
入社提交（游客+登录）与审批（含通知与重复审批拒绝）、管理员保护规则
（SELF_DISABLE/ROOT_PROTECTED/FORBIDDEN/LAST_ADMIN/NO_CHANGE）、注册→欢迎通知事件。

### 3b3. 子阶段 2.5 集成测试（管理员角色/审计删除）

```bash
uv run python -m pytest tests/integration/test_phase2_5_admin.py -v --no-cov
```

覆盖：角色 CRUD（权限自动创建/全量替换/用户数）、系统角色删除保护、审计日志删除（单条 + 批量）。

### 3b4. Phase 3 集成测试（活动模块）

```bash
uv run python -m pytest tests/integration/test_phase3_events.py -v --no-cov
```

覆盖：活动 CRUD + 自动归档、报名流（重复 409/名额满 409/取消重报）、签到码生成与核销
（无效码/重复使用）、批量更新 + 统计、活动设置读写/重置。

### 3b5. Phase 4 集成测试（社区模块）

```bash
uv run python -m pytest tests/integration/test_phase4_community.py -v --no-cov
```

覆盖：版块+主题（slug 冲突/反范式计数/浏览去重）、回复+互动（楼中楼/点赞收藏）、
审核（隐藏/恢复/置顶/加精/硬删除）、博客（slug 唯一/发布/归档/点赞/系列）、
成员与 Feed 聚合（标签筛选/三源合并/统计）。

> 纯单元测试（TOTP RFC 6238 向量、加密交叉验证、scrypt 兼容）已在本机通过，
> 无需 PG：`tests/core/test_totp*.py`、`tests/core/test_password_compat.py`。

### 3c. 前后端联调（Phase 1 BFF 切换）

前端已转换为薄转发（19 个路由，JWT 存 BFF HttpOnly Cookie + 401 静默刷新）。
后端可运行后联调：

```bash
# 1. 起后端（本仓库）
uv run python run.py --env 1        # http://localhost:9000（SITE_URL 指向 BFF）
# 2. 起前端（CS-Web-Frontend，BACKEND_URL 指向后端）
cp .env.example .env
# .env: BACKEND_URL=http://localhost:9000
pnpm dev                            # http://localhost:2333
```

验证清单：
- [ ] 注册（验证码）→ 自动登录 → /api/auth/me 返回完整用户
- [ ] 登录 → 2FA 启用后返回 requires2FA → 2FA 完成登录
- [ ] 修改密码 → 旧 access 失效、自动静默刷新
- [ ] GitHub OAuth 入口/回调（未配置时入口 404）
- [ ] 设备列表 / 远程登出 / 头像上传 / 预设头像
- [ ] 忘记密码 → 管理员批准 → 默认密码登录

### 4. 表结构与约束抽查

```sql
-- 表清单（应为 42 张业务/框架表 + alembic_version）
\dt

-- 唯一约束抽查
\d settings          -- 应有 ux_settings_module_key (module, key)
\d event_registrations -- 应有 ux_event_registrations_unique (user_id, event_id)
\d two_factor_auth   -- 应有 fk_two_factor_auth_user_id_users (ON DELETE CASCADE)

-- partial unique index（论坛浏览去重）
\d forum_topic_views -- 应有 idx_forum_topic_views_unique_user / _ip（WHERE 子句）

-- 循环外键（forum_topics.last_reply_id -> forum_replies）
\d forum_topics      -- 应有 fk_forum_topics_last_reply_id_forum_replies

-- users 业务字段
\d users             -- display_name/bio/avatar_url/avatar_type/github_url/website_url/github_id/tech_tags

-- refresh_tokens 设备字段（Phase 1）
\d refresh_tokens    -- 应有 ip_address / user_agent

-- JSONB 列
\d exam_attempts     -- answer 为 text；tech_tags 类列应为 jsonb
```

### 5. 约束生效冒烟（可选但推荐）

```bash
uv run python - <<'PY'
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+asyncpg"))
    async with engine.connect() as conn:
        # 唯一约束：重复 (module,key) 应报 UniqueViolation
        await conn.execute(text("INSERT INTO settings(module, key, value) VALUES ('m','k','v')"))
        try:
            await conn.execute(text("INSERT INTO settings(module, key, value) VALUES ('m','k','v2')"))
            print("FAIL: unique constraint not enforced")
        except Exception as e:
            print("OK unique:", type(e).__name__)
        await conn.rollback()
        # 外键：指向不存在的用户应报错
        try:
            await conn.execute(text("INSERT INTO login_history(user_id, success) VALUES (999999, true)"))
            print("FAIL: FK not enforced")
        except Exception as e:
            print("OK fk:", type(e).__name__)
        await conn.rollback()
    await engine.dispose()

asyncio.run(main())
PY
```

### 6. 回滚往返

```bash
uv run alembic downgrade -1       # 回滚到 e6a4b91d70c2：33 张业务表应消失，users 业务列移除
uv run alembic upgrade head       # 再升级回 head
```

### 7. 测试套件

```bash
# 需要 domefff_test 测试库（库名含 test）；Redis 缺失时限流/缓存自动降级
uv run python -m pytest -x -q --no-cov
# 或仅跑模型无关的单元测试：
uv run python -m pytest -x -q --no-cov -m "not integration"
```

---

## 四、已知约定（比对时留意，勿当 drift 误报）

| 项 | 说明 |
|---|---|
| `avatar_type` 两段式 | 迁移先加 `server_default='initial'` 再 DROP DEFAULT：存量行可写且元数据无默认值 |
| Python 侧默认值 | 所有列默认值在模型 Python 侧（`default=...`），DDL 无 `DEFAULT` 属预期 |
| JSONB | `JSONDict = JSON().with_variant(JSONB(), "postgresql")`，PG 落成 JSONB |
| 主键自增 | Integer PK 落成 SERIAL，无独立序列对象 |
| FTS5 / tsvector | 论坛全文搜索不在本迁移范围（Phase 4 单独处理） |
| 索引名 | 单列 `ix_<table>_<col>`，复合/partial 用显式名（`idx_*` / `ux_*`） |

---

## 五、验证后回报（回到迁移维护者）

1. `alembic heads` / `alembic check` 输出原文
2. 冒烟脚本各断言结果（OK/FAIL）
3. `alembic upgrade head` 耗时与日志尾部
4. 如有 drift：autogenerate 差异内容
5. pytest 汇总行（passed/skipped）
