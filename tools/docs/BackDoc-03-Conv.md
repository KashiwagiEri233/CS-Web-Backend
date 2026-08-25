# BackDoc-03-Conv：后端工程约定（DDD 实现 / 测试分层 / API 规范 / 依赖配置 / 日志异常）

> 更新人：3yearsZ
> 更新日：2026-08-20
> 版本：1.0.1（版本基线对齐 1.0.1；DDD api→services→repositories→models→schemas→core；FastAPI Depends；Pytest 分层覆盖率目标）
> Diátaxis：R（Reference · 规范参考 · 后端实现级约定 L2 唯一权威）
> 适用读者：后端 Python 贡献者、后端 reviewer、模块 Owner、数据库迁移操作者
> 变更触发：新增/重命名后端模块 / DDD 分层规则变更 / 测试覆盖率阈值调整 / 依赖管理工具或策略变动 / API 响应包装或错误码注册表变动 / 日志或中间件策略调整
>
> **SSOT（唯一权威）声明**：本文档是 CS-Web-Backend **后端 L2 实现级约定**的唯一权威输入。跨仓通用工程约定（命名门禁、版本三源、通用安全红线、所有权矩阵）以 [RootDoc-EngConv.md](../../../docs/RootDoc-EngConv.md) 为权威；实现级安全红线（鉴权/限流/密钥/异常/审计）以 [BackDoc-02-Sec.md](BackDoc-02-Sec.md) 为权威；模块契约的跨模块协作接口定义以 [BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md) 为权威；深层架构决策动机与 Arc42 完整章节以 [BackDoc-01-Arch.md](BackDoc-01-Arch.md) 为权威。
>
> **关联索引**：后端架构总览 → [BackDoc-01-Arch.md](BackDoc-01-Arch.md)；后端安全红线 → [BackDoc-02-Sec.md](BackDoc-02-Sec.md)；模块契约 → [BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md)；跨仓通用约定 → [RootDoc-EngConv.md](../../../docs/RootDoc-EngConv.md)；资源域命名门禁 → [RootDoc-ModuleMap.md](../../../docs/RootDoc-ModuleMap.md)

---

## 0. 文档速览：约束密度总表

| 章节 | 主题 | MUST 条数 | MUST NOT 条数 | SHOULD 条数 | MAY 条数 | 关键代码入口 |
|------|------|-----------|--------------|------------|----------|-------------|
| §1 | DDD 分层实现 + 模块目录结构 | 10 | 8 | 5 | 3 | `app/api/`、`app/services/`、`app/repositories/`、`app/models/`、`app/schemas/`、`app/core/` |
| §2 | 测试分层 + 覆盖率目标 + 夹具约定 | 8 | 7 | 5 | 2 | `tests/unit/`、`tests/integration/`、`tests/e2e/`、`tests/conftest.py`、`pyproject.toml coverage` |
| §3 | API 规范：响应包装 / 错误码注册表 / DTO 约定 | 9 | 7 | 5 | 3 | `app/core/exceptions.py`、`app/core/error_codes.py`、`app/api/deps.py`、`app/{domain}/schemas.py` |
| §4 | 依赖 / Alembic / 配置 / 环境变量规范 | 8 | 7 | 4 | 2 | `pyproject.toml`、`uv.lock`、`alembic/versions/`、`app/core/config.py`、`.env.example` |
| §5 | 日志 / 异常 / 中间件 / 性能实践 | 8 | 7 | 5 | 2 | `app/core/logging.py`、`app/middleware/`、`app/core/exceptions/`、`app/api/deps.py` |
| §6 | — | **43（合计）** | **36（合计）** | **24（合计）** | **12（合计）** | — |

---

## 1. DDD 分层实现 + 模块目录结构

### 1.1 概述（一句话定位）

后端采用 `DDD 分层 + 模块按资源域聚合` 的代码组织方式；每个资源域模块 `app/{domain}/` 内含 `api.py`（Router + Depends）、`services.py`（业务逻辑）、`repositories.py`（DAO）、`models.py`（ORM）、`schemas.py`（DTO）；禁止跨层跳过；模块间互调 MUST 通过 services 公开接口或 event bus（MVP 暂 services 直调）。

### 1.2 分层职责与目录清单

#### 1.2.1 DDD 六层职责表

| 层 | 路径 | 职责（该层只做这些事） | 禁止进入 |
|---|---|---|---|
| **api**（Controller） | `app/api/router.py` + `app/{domain}/api.py`（APIRouter） | 路由注册 + Depends 解析（db session、current_user、权限）+ 调用 services + 校验 schemas + 返回响应 | 禁止 db.execute、禁止直接访问 ORM models、禁止业务逻辑（if/else 超过 5 行） |
| **services**（Service） | `app/{domain}/services.py` 或 `app/{domain}/services/` 多文件 | 业务逻辑编排（跨 repositories）+ 领域规则校验 + 跨模块互调入口 + 事件发布 | 禁止直接写 Response、禁止直接操作 HTTP 请求对象、禁止自己拿 session |
| **repositories**（DAO） | `app/{domain}/repositories.py` 或 `app/{domain}/repositories/` 多文件 | 纯 CRUD（Get / List / Create / Update / Delete / Count / Exists）+ 复杂查询聚合（带 join/filter）+ 分页；返回 ORM 对象或 list[int] | 禁止业务 if/else、禁止权限判断、禁止写日志（按 LOG-01 合规除外） |
| **models**（Model） | `app/{domain}/models.py` 或 `app/models/{domain}_*.py` | SQLAlchemy ORM 映射：表名（蛇形复数）、列（蛇形）、关系、约束、索引；`__tablename__` 显式声明 | 禁止业务方法（`def send_email(self)` 之类禁止）、禁止 DTO 复用 |
| **schemas**（DTO） | `app/{domain}/schemas.py` 或 `app/{domain}/schemas/` 多文件 | Pydantic v2 输入/输出模型：Base → Create → Update → Response（SafeUser 白名单）+ 枚举（snake_case JSON） | 禁止直接继承 ORM model 到 Response（必须显式字段白名单） |
| **core**（基础设施） | `app/core/`（config、security、exceptions、logging、rate_limit、deps 全局） | 全局单例（Settings、Logger、RateLimiter、JWT 工具）+ Depends 公共函数 + 异常类 + 错误码注册表 | 禁止依赖任何业务模块（users/auth/exams …）；保持纯基础设施方向 |
| **middleware**（横切） | `app/middleware/`（rbac、rate_limit、request_id、api_usage、error_handler） | Starlette/FastAPI 中间件：请求前后处理；不持有业务状态 | 禁止直接 import services；必须用 Depends 或 request.state 透传 |

#### 1.2.2 模块目录结构标准（每个资源域 MUST 对齐）

```
app/{domain}/
├── __init__.py          # MUST 导出 APIRouter: from .api import router
├── api.py               # APIRouter + Depends(...) + 调用 services
├── services.py          # 业务逻辑；若 > 300 行 → 拆 services/*.py
├── repositories.py      # DAO；若 > 300 行 → 拆 repositories/*.py
├── models.py            # ORM；若 > 5 张表 → 拆 models/*.py
└── schemas.py           # Pydantic；若 > 10 个模型 → 拆 schemas/*.py
```

**共享跨模块 Depends** 放 `app/api/deps.py`（如 `get_db`、`get_current_user`、`require_permission`），禁止各模块重复定义。

### 1.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. **每层职责边界 MUST 严格对齐 §1.2.1 表**；**MUST NOT** 跨层（例：api 层直接 `db.query(User)` 跳过 services/repositories；services 层直接构造 JSON Response）。
2. 每个资源域模块 **MUST** 按 §1.2.2 目录结构 6 文件/目录标准组织；**MUST NOT** 模块 3 文件以下（api/services 合并）或模块文件散落在 `app/` 根目录（`app/user.py` 单文件 = 例外：仅非资源域辅助工具）。
3. 模块 `__init__.py` **MUST** 导出 `router`（`from .api import router`）；`app/api/router.py` **MUST** 以 `include_router(domain.router, prefix='/api/v1/{domain}', tags=['{domain}'])` 注册。
4. services 函数签名 **MUST** 接受 `db: Session` + 业务参数，**MUST NOT** 自己从 `app.core.config` 单例拿 db session；调用 api 层 MUST 通过 `Depends(get_db)` 传入。
5. repositories 函数 **MUST** 返回 ORM 对象（或 list[ORM]、int、bool）；**MUST NOT** 返回 Pydantic schema（那是 services/api 层的职责）。
6. models **MUST** 显式写 `__tablename__`；**MUST NOT** 依赖 SQLAlchemy 自动从 class name 推断表名（防复数/缩写误推断）。
7. schemas Response 模型 **MUST** 独立声明（`UserResponse(BaseModel)`），**MUST NOT** `class UserResponse(User, BaseModel)` 从 ORM 继承。
8. Depends 公共函数（`get_db`、`get_current_user`、`require_permission`）**MUST** 唯一存放 `app/api/deps.py`；**MUST NOT** 在各模块 api.py 重复定义副本。
9. 跨模块调用 **MUST** 通过目标模块 services 公开函数（如 `from app.users.services import get_user`）；**MUST NOT** `from app.users.repositories import UserRepository` 直接跨模块 import DAO。
10. 新增模块 **MUST** 先在 RootDoc-ModuleMap.md 登记 8 项，再按本节创建文件；**MUST NOT** 先写代码后补。

**MUST NOT（禁止事项）：**
1. **MUST NOT** 在 `app/core/` 内 `from app.users ...` 反向导入业务模块（会造成 import cycle）；core 必须是 DAG 根节点，无业务依赖。
2. **MUST NOT** 在 `models.py` 里写「业务计算方法」（如 `def can_enroll_exam(self, user_id)` → 放 services 层）；models 只负责 ORM 映射。
3. **MUST NOT** 在 `schemas.py` 里写「数据库查询」（如 `@field_validator` 里查数据库）→ 校验要么客户端能自洽（纯字段），要么放 services 查库。
4. **MUST NOT** 模块 A services 直接 import 模块 B 的 models 并 `db.query(ExamModel)` → 必须经 B.services 公开方法。
5. **MUST NOT** 把 FastAPI Request 对象一路传到 services/repositories；需要 request_id / current_user 时 MUST 显式作为参数传入。
6. **MUST NOT** 直接在 api 层 `db.commit()`；services 层负责事务边界（一次业务动作一次提交 / 一次回滚）。
7. **MUST NOT** 模块目录混合单复数命名（`app/user/` + `app/users/` 同时存在）；资源域目录 **MUST** 复数（`users`、`exams`）。
8. **MUST NOT** 模块 api 使用非标准 tags（`tags=["用户模块（开发版）"]`）；**MUST** `tags=['{domain}']` 英文小写域对齐 OpenAPI。

**SHOULD（建议事项）：**
1. **SHOULD** 每个 services 函数 docstring 附「影响资源域 + 调用方（api/其他 services）+ 是否需事务（commit/rollback）」三行摘要；便于 reviewer 理解。
2. **SHOULD** 模块按域分文件大小阈值：services/repositories > 300 行，schemas > 10 个模型，models > 5 张表 → 拆子目录 `services/*.py` 等。
3. **SHOULD** 跨模块 services 调用处附 comment：`# cross-module via users.services (see BackDoc-ModuleContracts §3)` 指向模块契约。
4. **SHOULD** 引入 mypy `disallow_untyped_decorators = true`，所有 api/services/repositories 函数 MUST 加类型注解。
5. **SHOULD** 新模块模板使用 `app/_template/`（如有）一键生成目录骨架 + 最小路由 + pytest 夹具；避免每次手搓漏文件。

**MAY（可选配置）：**
1. 小模块（只有 1~2 条路由 + 50 行 services）**MAY** api + 少量 services 合并到 `app/{domain}/api.py`，但 **MUST** 标注 `# TODO: scale > 100 lines → split services.py` 并配 issue 追踪。
2. **MAY** 引入 `Dependency Injector` 等 DI 容器替代手工 Depends；但 MVP MUST 保持 FastAPI Depends 原生最简，避免引入额外复杂度。
3. **MAY** 对 `{domain}/models.py` 引入 `declarative_base_custom` 基类（自动 `created_at`、`updated_at`、`id = Column(Integer, primary_key=True)`）统一公共字段。

### 1.4 自检 CheckList

- [ ] 六层职责边界：grep 检查 0 处跨层违规（api 层 db.query、services 层 Response 构造等）
- [ ] 模块目录结构：所有 `app/{domain}/` 对齐 §1.2.2；6 文件齐全或 >阈值已拆
- [ ] router 汇总：`app/api/router.py` include_router 前缀 `/api/v1/{domain}` 正确 + tags 英文小写
- [ ] schemas Response：未从 ORM 继承；显式字段白名单
- [ ] Depends 公共函数：仅 `app/api/deps.py` 定义，0 处模块重复副本
- [ ] 跨模块调用：仅 services 公开接口；0 处跨模块 import repositories/models

---

## 2. 测试分层 + 覆盖率目标 + 夹具约定

### 2.1 概述（一句话定位）

后端测试 MUST 分三层（Unit / Integration / E2E），职责清晰、互不代替。Unit 测 services/schemas/工具函数，以内存 SQLite / mock db 为主；Integration 测 repositories + Alembic + 实际 PostgreSQL 行为；E2E 测 api 路由全程（鉴权/限流/错误码全链路）。覆盖率目标：总体 **≥ 80%**，核心模块（users/auth/core/rate_limit）**≥ 90%**；低于阈值 PR MUST 打回补测。

### 2.2 测试分层与夹具清单

#### 2.2.1 三层测试职责与位置

| 层 | 目录 | 测什么 | 用什么 DB | 用什么夹具 | 运行速度目标 |
|---|---|---|---|---|---|
| **Unit** | `tests/unit/{domain}/test_*.py` | services 业务逻辑、schemas 校验、core 工具函数（security/jwt/rate_limit）| 内存 SQLite 或 mock Session（不连真实 PG）| `mock_db`、`mock_user`、patch services 返回 | 单测 < 100ms / case，`make test` 优先跑 |
| **Integration** | `tests/integration/{domain}/test_*.py` | repositories CRUD、复杂 join 查询、Alembic 迁移 roundtrip（upgrade→downgrade）、并发写冲突 | 独立 test PG（Docker 起 `postgres:16-alpine` 或等效）| `db_session`（事务级 rollback fixture）、`migrated_db`、`test_data_{domain}` 种子数据 | ≤ 1s / case；CI 全跑 |
| **E2E** | `tests/e2e/test_*.py` | 完整 HTTP 请求路径：`TestClient`（FastAPI）→ api → services → repositories → PG → Response；覆盖：鉴权、限流、错误码、RBAC、审计落库 | 独立 e2e PG（同 Integration，但 fixtures 不回滚、每次建+删）| `client`（TestClient）、`auth_headers_admin/member/anon`、`seed_all` | ≤ 3s / case；CI 全跑 + 发布前 `make test-e2e` MUST 全绿 |

#### 2.2.2 覆盖率目标与阈值（pyproject.toml coverage:run）

| 路径 / 模块 | 覆盖率下限（line %） | 备注 |
|---|---|---|
| 总体（`app/` 全目录） | **≥ 80%** | PR 合并前 `pytest --cov=app --cov-report=term-missing` MUST 达标 |
| `app/core/`（配置/安全/限流/异常/错误码） | **≥ 90%** | 基础设施关键路径；缺 case MUST 在 PR 描述说明风险 |
| `app/auth/` + `app/users/`（认证+鉴权+用户） | **≥ 90%** | 安全红线 RBAC-01、LOG-01 的代码；缺 case = 高风险 |
| `app/middleware/rbac.py` + `rate_limit.py` | **≥ 90%** | 同上 |
| `app/{其他业务域}/services.py` | ≥ 80% | 业务规则 |
| `app/{其他业务域}/repositories.py` | ≥ 75% | Integration 测试覆盖；纯 CRUD 少量分支 |
| `app/{其他业务域}/models.py` + `schemas.py` | ≥ 65% | 主要通过 Integration/E2E 连带覆盖 |
| `app/admin/`（管理员审计路径） | ≥ 80% | 1.0.0 门槛 #2：管理员写操作审计不丢 |

#### 2.2.3 必用夹具（conftest.py 全局或模块级）

| 夹具名 | 用途 | 所在位置 |
|---|---|---|
| `mock_db` | Unit 层用的内存 SQLite Session；回滚不 commit | `tests/conftest.py`（全局） |
| `db_session` | Integration 层：真实 PG + 事务级 rollback（每个 test 独立事务） | `tests/conftest.py` |
| `migrated_db` | Alembic upgrade head 后的 PG；用于 migration roundtrip | `tests/conftest.py` |
| `client` | FastAPI TestClient（带 override db=db_session） | `tests/conftest.py` |
| `auth_headers_{role}` | `Authorization: Bearer <token>` 预生成；role = admin/member/club_leader；对应 `testdata_users` | `tests/conftest.py` 或 `tests/auth/conftest.py` |
| `test_data_{domain}` | 业务域种子数据；每个业务域 `tests/{unit|integration}/{domain}/conftest.py` 提供 | 模块级 |

### 2.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. **测试分层职责 MUST 严格对齐 §2.2.1 表**；Unit **MUST NOT** 连真实 PG；E2E **MUST NOT** mock 掉 services/repositories（否则 E2E 假绿）。
2. **覆盖率阈值 MUST 达标**；PR **MUST** 本地跑 `pytest --cov=app --cov-report=term-missing` 与 CI 一致，低于阈值 **MUST** 打回补测；**MUST NOT**「忽略 1% 差距先合」。
3. **新函数/新类 MUST 伴随测试**；新增 services 方法 / repositories 查询 / api 路由 **MUST** 在同一 PR 提供至少 Unit 覆盖（核心 MUST 同时提供 E2E/Integration）。
4. **夹具幂等与独立**：每个测试 **MUST** 独立可重跑（`pytest tests/e2e/test_foo.py -k test_bar` 单独跑 MUST 通过）；**MUST NOT** 测试 A 通过与否依赖测试 B 先执行留下的状态。
5. **`db_session` 事务级回滚**：Integration 层夹具 **MUST** 每个 case 单独事务 + rollback；**MUST NOT** case 末尾显式 delete 清理（易漏 + 慢）。
6. **E2E 必须覆盖鉴权 + 权限校验**：每条写路由 **MUST** 至少 3 个 E2E case：匿名 401、member 403、admin 200/201；对齐 RBAC-01。
7. **`migrated_db` roundtrip 测试**：Alembic 迁移新增后 **MUST** 补 Integration 测试：`upgrade head → 插入种子 → downgrade -1 → upgrade 再 head` 无报错。
8. **测试命名约定 MUST 统一**：`test_{动词}_{预期}_{条件}`，如 `test_create_user_returns_201_with_valid_input`；**MUST NOT** `test_user1`、`test_it_works` 无意义命名。

**MUST NOT（禁止事项）：**
1. **MUST NOT** 用 `unittest.mock.patch("app.users.services.get_user")` 等长字符串硬编码路径作为 mock 首选；**MUST** 依赖注入（patch 通过 Depends override）或依赖接口协议，避免重构路径时大面积改 mock。
2. **MUST NOT** 跳过测试（`@pytest.mark.skip`）不附说明；skip **MUST** 附 `reason="Issue #123: blocked by upstream PG 版本"`，并追踪。
3. **MUST NOT** 在测试中 print 真实 secret / token 明文；对齐 LOG-01 + KEY-01。
4. **MUST NOT** 一个测试断言 > 5 个独立分支；拆为多个 test，case 命名明确区分；便于失败时一眼定位。
5. **MUST NOT** 为了覆盖率而写「断言只看 return 类型 = None」无意义测试；覆盖率是工具，不得为了达标造假。
6. **MUST NOT** `tests/` 目录结构与 `app/` 完全不同（如 test_users.py 放根 + test_auth 在子目录）；MUST 镜像：`tests/{unit|integration|e2e}/{domain}/test_*.py`。
7. **MUST NOT** E2E 用「先起 uvicorn 子进程 + sleep」异步耦合；**MUST** 用 FastAPI TestClient（内置）同步驱动。

**SHOULD（建议事项）：**
1. **SHOULD** 每个 services 函数 docstring 下附「# tests: unit ×2 + integration ×1 + e2e ×2」目标覆盖路径摘要；便于补测时对齐。
2. **SHOULD** 对高频随机失败（flaky）测试标记 `@pytest.mark.flaky(reruns=2)` + 附根因 issue；每月 review flaky 列表。
3. **SHOULD** 提供 `pytest --runslow` 标签；长耗时 E2E 默认不跑本地、仅 CI 跑，加速开发迭代。
4. **SHOULD** 覆盖率报告 CI 阶段上传到代码质量平台（如 Codecov）并设阈值门禁；PR 覆盖率下降 > 2% 自动打 warning。
5. **SHOULD** Property-based 测试（hypothesis）对 Pydantic schemas 校验与复杂 services 逻辑至少覆盖 1 个，抓边界值（空字符串、极长、Unicode、SQL 注入字符）。

**MAY（可选配置）：**
1. **MAY** MVP 期 E2E 对 SSE / LLM streaming 路径简化为「连接建立 + 首块返回」；完整版 MUST 补全完整时序。
2. **MAY** 引入测试数据工厂（factory_boy）替代手工构造 ORM 对象；但 **MUST** 与 `test_data_{domain}` 夹具保持一致。

### 2.4 自检 CheckList

- [ ] 三层测试职责分离：Unit 0 处连真实 PG；E2E 0 处 mock services/repositories
- [ ] 覆盖率：`pytest --cov=app --cov-report=term-missing` 总体 ≥ 80%、core/auth/users ≥ 90%
- [ ] 新 PR：新增函数伴随测试；写路由 3 种角色 case（anon/member/admin）齐全
- [ ] 夹具独立：任意单 test 用例独立重跑通过；无 A→B 顺序依赖
- [ ] 命名：`test_{动词}_{预期}_{条件}`；0 处 `test_user1` / `test_it_works`
- [ ] 无意义 skip 0；skip 全带 issue 追踪 reason
- [ ] `migrated_db` roundtrip：upgrade→downgrade→upgrade 0 报错

---

## 3. API 规范：响应包装 / 错误码注册表 / DTO 约定

### 3.1 概述（一句话定位）

后端 `/api/v1` 冻结契约（RootEngConv §1）对所有响应 MUST 统一包装为 `Envelope`（`success + code + message + data`）；错误响应必须走 `app/core/error_codes.py` 注册表，不得硬编码 `code: "E_xxx"` 字符串。DTO 输入/输出 MUST 字段白名单；分页格式/排序语法/错误提示 i18n key 与前端契约层对齐。

### 3.2 Envelope 包装 + 错误码注册表 + DTO 清单

#### 3.2.1 Envelope 响应格式（所有 `/api/v1/*` MUST 对齐）

| 字段 | 类型 | 成功 | 失败 | 备注 |
|---|---|---|---|---|
| `success` | bool | `true` | `false` | 成功/失败二元判断（不依赖 HTTP status）|
| `code` | str | `"OK"`（单点入口 `ResponseCode.OK`） | `"E_AUTH_001"` 等；来自 `error_codes.py` 注册表 | **禁止裸字符串 `"OK"` 四处写** |
| `message` | str | 人类可读摘要（英文）；i18n key 可选放 `i18n_key` | 人类可读错误摘要；对应 `ErrorCode.message` | |
| `data` | T（泛型）或 null | 响应体（对象 / 数组 / null） | 可选：`details` 额外字段 | |
| `i18n_key`（可选）| str | 成功 i18n key | 失败 i18n key（同 `ErrorCode.i18n_key`） | 前端契约层消费 |
| `trace_id`（可选）| str | `request.state.request_id` | 同左；错误排查用 | 中间件注入 |
| `pagination`（分页专用）| object | 见 §3.2.2 | null | 仅 List 接口 |
| HTTP status | int | 200（查）、201（创建）、204（删空响应 data=null） | 4xx（客户端错）、5xx（服务器错） | 与 `success` 语义 MUST 对应 |

#### 3.2.2 分页格式（所有 `GET /api/v1/{domain}` 列表接口 MUST 对齐）

```jsonc
{
  "success": true,
  "code": "OK",
  "message": "Successfully retrieved {domain}",
  "data": [...],                         // 数组
  "pagination": {
    "page": 1,                           // int，从 1 开始
    "page_size": 20,                     // int，默认 20，最大 MUST ≤ 100
    "total": 42,                         // int，总条数（count 查询）
    "total_pages": 3,                    // int，ceil(total/page_size)
    "has_prev": false,
    "has_next": true,
    "sort_by": "created_at",             // str，允许字段白名单
    "sort_order": "desc"                 // "asc" | "desc"
  }
}
```

#### 3.2.3 错误码注册表 `app/core/error_codes.py` 结构

每个错误码 **MUST** 四元组登记：

```python
@dataclass
class ErrorCode:
    code: str           # "E_AUTH_001"（E_模块_三位编号；模块前缀 AUTH/USER/EXAM/ASSOC/ACT/COMM/AI/ADMIN/SYS/VAL/RATE）
    message: str        # 英文摘要
    http_status: int    # 4xx/5xx
    i18n_key: str       # "errors.auth.invalid_credentials"（前端契约对齐）
    severity: Severity  # INFO/WARN/ERROR/FATAL（日志分级用；FATAL 触发告警）
```

#### 3.2.4 DTO 字段约定

| 类别 | 规则 |
|---|---|
| **Create DTO** | `UserCreate(BaseModel)`；字段与 HTTP 请求体一一对应；校验用 Pydantic v2 `@field_validator` + `Field(ge=..., max_length=...)` |
| **Update DTO** | `UserUpdate(BaseModel)`；所有字段 Optional（部分更新语义）；`None`= 不改；区分「清值 = `""` / `0` / `[]`」vs「不改 = None」 |
| **Response DTO** | `UserResponse(BaseModel)`；字段白名单；MUST 不含 password_hash、totp_secret、内部枚举；对齐 SafeUser |
| **List Query DTO** | `UserListQuery(BaseModel)`：`page: int = Field(1, ge=1)`、`page_size: int = Field(20, ge=1, le=100)`、`sort_by: Literal['created_at','email'] = 'created_at'`、`sort_order: Literal['asc','desc'] = 'desc'` + 业务筛选字段 |
| **枚举 DTO** | JSON 值 snake_case；`UseValuesOrValidators` 配合；禁止 PascalCase |
| **时间字段** | 响应 DATETIME **MUST** UTC iso 字符串；消费端本地转时区；created_at / updated_at 命名统一 |

### 3.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. **所有 `/api/v1/*` 响应 MUST 包装为 §3.2.1 Envelope**；**MUST NOT** 裸返回 JSON 对象（`return user_response`）、**MUST NOT** 业务代码自行组装 `{"result": ...}` 非标准结构。
2. **成功 code MUST = `ResponseCode.OK`（单点常量）**；**MUST NOT** 各模块 `"OK"` 字符串四处硬编码。
3. **失败 code MUST 来自 `error_codes.py` 注册表**；**MUST NOT** api/services 层 `code="E_USER_007"` 裸字符串（避免重复编号 / 漂移）。
4. **错误码编号前缀 MUST 与模块对齐**（AUTH/USER/EXAM/ASSOC/ACT/COMM/AI/ADMIN/SYS/VAL/RATE）；新增模块 MUST 在注册表登记前缀；**MUST NOT** 跨模块前缀混用（如考试错误放 AUTH）。
5. **分页接口 MUST 输出 §3.2.2 pagination 七字段**；`page_size` **MUST** `≤ 100`；**MUST NOT** `page: 0` 或 `sort_by` 不在白名单（SQL order by 注入防）。
6. **Response DTO MUST 字段白名单独立声明**；**MUST NOT** 从 ORM 继承（防泄露 password_hash / totp 等敏感字段）。
7. **Update DTO 部分更新语义 MUST 清晰**；`None`= 不改、空值显式传 `""` / `0` / `[]`；**MUST NOT** 「所有字段必传 + 用默认值覆盖数据库」全量覆写。
8. **时间字段 MUST UTC iso 字符串**；created_at / updated_at 命名 **MUST** 统一；**MUST NOT** 响应里出现本地时区字符串或 Unix 秒时间戳。
9. **List Query DTO `sort_by` MUST `Literal` 白名单**；**MUST NOT** `sort_by: str` 任意字符串直接拼 order by。

**MUST NOT（禁止事项）：**
1. **MUST NOT** HTTP 200 且 `success=false`（语义冲突）；4xx/5xx 必须对应 `success=false`，2xx 必须对应 `success=true`（除 204 空响应特殊）。
2. **MUST NOT** 错误 `message` 直接把异常堆栈 / SQL 错误文本塞进响应；对齐 BackDoc-02-Sec §2（统一异常不泄露内部信息）。
3. **MUST NOT** 同一含义多错误码（如「用户不存在」同时有 `E_USER_003` + `E_SYS_002`）；注册表 **MUST** 单一权威，按语义消重。
4. **MUST NOT** DTO 中混用 snake_case + camelCase 字段名；响应 **MUST** 全 snake_case（RootEngConv §1）。
5. **MUST NOT** Create DTO 用 `Optional` 字段作为「可选字段」；创建字段 **MUST** 必填用非 Optional、可选字段要 `Optional` + 明确默认值。
6. **MUST NOT** 分页 `sort_order` 允许 `"DESC"` 大写或 `"-created_at"`（Django 风格）；**MUST** `Literal["asc","desc"]` 归一化。
7. **MUST NOT** 直接在响应里塞 `datetime.datetime` 对象（不序列化）；**MUST** Pydantic model 自动转 iso（或 `model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})` 全局配置）。

**SHOULD（建议事项）：**
1. **SHOULD** 每个错误码提供单元测试：触发该错误的集成 case → 断言 `code == ErrorCode.E_AUTH_001.code` + HTTP status 正确；避免注册表 drift。
2. **SHOULD** `error_codes.py` 注册表导出 JSON（`uv run scripts/dump_error_codes.py`）→ 前端契约层消费生成 `errors.ts` 常量映射；保持三端 i18n key 对齐。
3. **SHOULD** DTO `field_validator` 规范化（邮箱小写、去前后空格、全角半角归一化）；防止重复数据（`Foo@bar.com` vs `foo@bar.com`）。
4. **SHOULD** 分页默认 `page_size=20`，业务特殊情况（考试题目）**SHOULD** 设 50/100 并单独说明；避免过大 page_size 导致慢查询。
5. **SHOULD** 响应 Envelope 统一由 `app/core/exceptions/handler.py` 中 `APIResponse` 工具类生成；api 层禁止手搓字典。

**MAY（可选配置）：**
1. **MAY** 引入 `strawberry`/GraphQL 提供内部管理端查询（不对外）；但 `/api/v1` 外部契约 MUST 保持 REST JSON，不得引入双契约。
2. **MAY** 响应体额外附带 `_links` HATEOAS（REST 成熟度 L3）；但 MVP **SHOULD** 保持最简结构，不强制。
3. **MAY** 部分高频错误（如 401、403、429）在 CI 通过 `assert error_code.occurrences >= 1` 反向验证触发路径可达；防漏。

### 3.4 自检 CheckList

- [ ] Envelope：`grep -r "return {" app/` 0 处裸 JSON；全部走 `APIResponse.success()` / `APIResponse.error()` 工具
- [ ] 错误码注册表：E_前缀与模块一一对应；0 处重复编号；0 处裸字符串 `code="..."`
- [ ] HTTP status ↔ success 语义一致：2xx→true、4xx/5xx→false
- [ ] 分页七字段齐全；`page_size ≤ 100`；`sort_by` Literal 白名单
- [ ] Response DTO：独立声明；字段白名单不含 password_hash/TOTP/internal
- [ ] 时间 UTC iso；created_at/updated_at 命名统一；0 处本地时区或 Unix 时间戳
- [ ] 错误码单测覆盖率：≥ 80% 错误码有触发 case

---

## 4. 依赖 / Alembic / 配置 / 环境变量规范

### 4.1 概述（一句话定位）

后端使用 `uv` 管理依赖、`Alembic` 线性迁移链、`Pydantic-Settings` 配置加载；本节规定依赖管理流程、迁移链规则、配置组织结构、环境变量最小知原则与 `.env.example` 模板同步规则。跨仓通用版本三源同步与 Alembic 线性链原则（RootEngConv §2）为上位约束，本节补充实现级细节。

### 4.2 依赖 / Alembic / 环境变量清单

#### 4.2.1 依赖分层（`pyproject.toml` [project] optional-dependencies 分组）

| 组名 | 包含内容 | 用在何处 |
|---|---|---|
| `[project].dependencies`（默认核心） | FastAPI、SQLAlchemy、Alembic、Pydantic v2、psycopg、bcrypt、PyJWT、python-multipart、redis-py 等运行时最小集 | 生产 Docker 镜像；默认 `uv sync` 必装 |
| `[project.optional-dependencies].dev` | ruff、mypy、pytest、pytest-cov、hypothesis、factory_boy、pre-commit 等开发工具 | `uv sync --extra dev` 本地开发 |
| `[project.optional-dependencies].test` | pytest + pytest-cov + httpx(TestClient) 最小集 | CI 专用；避免 dev 太重 |
| `[project.optional-dependencies].ai` | langchain、openai、langsmith、tiktoken 等 LLM 集成 | AI 模块用户按需；不进入生产默认镜像除非 env `ENABLE_LLM=true` |
| `[project.optional-dependencies].oauth` | authlib、httpx OAuth client 等 | GitHub/Google OAuth 预留；MVP 默关 |

#### 4.2.2 Alembic 实现级细节（在 RootEngConv §2 线性链基础上）

| 项 | 规则 |
|---|---|
| 迁移 docstring **MUST** 三行头 | `"""<一句话描述迁移内容>` `Revises: <down_revision_id>` `# Domain: <domain>`（`# Date: YYYY-MM-DD` 可选） |
| upgrade/downgrade **MUST** 可回滚 | `upgrade()` 加列/表/索引；`downgrade()` 对应删/还原；禁止「只升级不降级」 |
| 大数据量表加索引 **MUST** `CREATE INDEX CONCURRENTLY` | PostgreSQL；避免全表锁；Alembic 用 `op.execute()` 手写 + `transaction_per_migration=True` 关闭事务包裹 |
| 删除列/表 **MUST** 先兼容窗口再删 | MINOR 版本标记列 `nullable=True` + 业务不再读 → 下一 MAJOR 才删列；对齐 `/api/v1` 冻结契约变更四阶段 |
| 迁移 MUST 幂等 | `IF NOT EXISTS` / `IF EXISTS` 合理使用；防止重复执行导致错误 |

#### 4.2.3 环境变量组织（`app/core/config.py` Settings + `.env.example`）

| 类别 | 变量前缀 | 示例 | 规则 |
|---|---|---|---|
| **安全类（高敏）** | `SECRET_*` / `*_PASSWORD` / `*_API_KEY` / `*_SECRET` | `SECRET_KEY`、`DB_PASSWORD`、`LANGSMITH_API_KEY` | `SecretStr` Pydantic；日志打印时 `get_secret_value()` 显式；默认值 MUST **空**（禁止默认 `my-secret`） |
| **DB 连接** | `DB_*` | `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_NAME`、`DB_URL` | `DB_URL` 优先（合成 DSN）；其余字段作为「未设 DB_URL 时拼接」 |
| **功能开关** | `ENABLE_*` / `DISABLE_*` | `ENABLE_LLM`、`ENABLE_OAUTH_GITHUB`、`DISABLE_RATE_LIMIT` | bool；默认 false / true（保守默认），不得反向 |
| **限流** | `RATE_LIMIT_*` | `RATE_LIMIT_DEFAULT_PER_MINUTE`、`RATE_LIMIT_AUTH_PER_MINUTE` | 见 BackDoc-02-Sec §3；默认值 MUST 与 BackSec 一致 |
| **JWT** | `ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`、`ALGORITHM` | 见 BackDoc-02-Sec §1；ALGORITHM 默认 `HS256` |
| **跨仓/部署** | `TRUST_PROXY`、`BACKEND_CORS_ORIGINS`、`ALLOWED_ORIGINS` | TRUST_PROXY 见部署；允许 origin 必须是具体列表或 JSON 字符串列表 |
| **日志/调试** | `LOG_LEVEL`、`DEBUG` | `DEBUG=true` 仅限本地开发；生产 MUST false |
| **第三方集成** | `OAUTH_*`、`LANGSMITH_*`、`SMTP_*` | 默认空串；为空即功能禁用，不得抛启动错误 |

`.env.example` **MUST** 列出所有环境变量，格式：
```dotenv
# 必填（生产 MUST 手动填入）
SECRET_KEY=
DB_URL=
# 可选（可留空 / 用默认）
# ACCESS_TOKEN_EXPIRE_MINUTES=15
```

### 4.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. **依赖管理 MUST 走 `uv add/remove` + `uv.lock` 同步**；**MUST NOT** 手工编辑 `pyproject.toml` 依赖版本后不跑 `uv lock`，**MUST NOT** 修改 `uv.lock` 不跑 `uv sync`。
2. **依赖分层 MUST 对齐 §4.2.1 组**；**MUST NOT** 把 `ruff` 等开发工具放入默认 dependencies（导致生产镜像变大 + 引入攻击面）。
3. **Alembic 迁移链（线性链 + 唯一 head + 可回滚 + Domain 标注）** 四条 **MUST** 同时满足；`alembic heads` 仅 1 条、`alembic check` 0 diff（RootEngConv §2 上位）。
4. **环境变量高敏类 MUST 用 `SecretStr`**；**MUST NOT** `print(settings.SECRET_KEY)` / `logger.info(f"... {settings.DB_PASSWORD}")`；必须 `.get_secret_value()` 显式使用。
5. **`.env.example` MUST 与 `config.py` 字段双向 1:1 同步**；新增配置 **MUST** 同时加两处；**MUST NOT** 配置有默认值却不在 example 说明。
6. **功能开关默认 MUST 保守**（`ENABLE_*` 默认 false，`DISABLE_*` 默认 true）；**MUST NOT** 新功能默认开启导致生产泄露。
7. **依赖升级 MUST 最小化升级跨度**；同一 PR 不 > 3 个大版本升级；**MUST** `uv add --upgrade-package foo` 后 `make ci` 全绿。
8. **`.env` 文件 MUST 进 `.gitignore`**；**MUST NOT** 被提交；CI / 生产通过环境变量或 secret manager 注入。

**MUST NOT（禁止事项）：**
1. **MUST NOT** 把真实 secret 写入 `pyproject.toml` / `config.py` 默认值 / alembic `env.py` / conftest.py 任何 Git 可追踪文件（对齐 KEY-01）。
2. **MUST NOT** 在迁移中执行「跨表批量数据修复」（如 `UPDATE users SET email = lower(email)`）放在 schema migration；**MUST** 用独立「数据迁移脚本」`scripts/migrate_*.py` 手动运行（避免长时间锁表 + Alembic 迁移无法回滚数据变更）。
3. **MUST NOT** 生产部署 `DEBUG=true`；**MUST NOT** 响应里返回 `debug: true` + `stacktrace: [...]` 字段。
4. **MUST NOT** 把 `SECRET_KEY` 同时设为 TOTP 加密 / OAuth state / JWT 签名多用途；不同用途 SHOULD 派生独立密钥（`TOTP_ENCRYPTION_KEY`、`OAUTH_STATE_KEY`），统一由 RootSec §4 管理。
5. **MUST NOT** 允许未登记的「野生配置」（直接 `os.getenv("MY_CUSTOM_VAR")` 未在 `Settings` 类声明）；所有环境变量 **MUST** 集中在 `config.py` 管理。
6. **MUST NOT** 生产构建 `--extra dev --extra ai --extra oauth` 全装；生产镜像 **MUST** 默认 core + 按需开关（`ENABLE_LLM=true` 时装 ai 组或镜像分层）。
7. **MUST NOT** alembic `downgrade()` 留 `pass` 或 `raise NotImplementedError()`；可回滚 = 可降级（即使业务不回滚也要支持安全回滚）。

**SHOULD（建议事项）：**
1. **SHOULD** 依赖声明在 `pyproject.toml` 上方加注释分组：`# Web framework`、`# Database`、`# Security`、`# Dev tools` 分组管理。
2. **SHOULD** 每次大版本 Alembic 迁移（如加新表 > 3 张）PR 附「迁移步骤」：先 `alembic upgrade head` → 再部署后端 → 最后切流量；防止迁移未应用时新代码命中「relation not exists」。
3. **SHOULD** 配置变更同步更新三处：`.env.example` + `app/core/config.py` + 根仓 `.env.example` 对齐（跨仓）。
4. **SHOULD** `uv run pip-audit` 或 `uv audit` 每周 CI 跑一次，中危以上依赖 MUST 在下个 MINOR/PATCH 升级。

**MAY（可选配置）：**
1. **MAY** 使用 `Dependabot` 或 `Renovate` 自动开依赖升级 PR；但高敏（cryptography、sqlalchemy、jwt）SHOULD 人工 review。
2. **MAY** 对 PG 超大表迁移引入 `pg_repack` / `pg_cron` 在线迁移工具；但 MUST 做 DBA 评估 + 预演环境验证。

### 4.4 自检 CheckList

- [ ] 依赖：`uv sync` 成功；`uv.lock` 最新；分层组（core/dev/test/ai/oauth）正确；无 dev 进默认依赖
- [ ] Alembic：1 head + 可回滚 + Domain 标注 + `alembic check` 0 diff；downgrade 0 `pass`
- [ ] 配置：SecretStr 覆盖高敏；`.env.example` 与 Settings 1:1；功能开关默认保守
- [ ] `.env`：.gitignore；0 处 commit 历史含真实 secret（`gitleaks` 若启用）
- [ ] 生产镜像：`DEBUG=false`；仅 core 依赖（或 ai/oauth 按开关）
- [ ] 数据迁移「批量修复」不混入 schema migration；独立脚本 `scripts/migrate_*.py`

---

## 5. 日志 / 异常 / 中间件 / 性能实践

### 5.1 概述（一句话定位）

本节规定后端的日志分级格式、异常统一处理、中间件横切顺序、以及性能最佳实践（DB N+1 查询、分页、大文件上传、缓存策略）。实现级安全约束（日志禁记 PII、异常脱敏、RBAC/限流中间件位置）与 BackDoc-02-Sec §1§2§3 上下位约束一致。

### 5.2 日志 / 异常 / 中间件 / 性能清单

#### 5.2.1 日志分级与字段（`app/core/logging.py` 统一配置）

| 级别 | 触发场景 | 示例 | 生产默认输出？|
|---|---|---|---|
| `FATAL/CRITICAL` | 系统不可用、启动失败、密钥缺失、数据库无法连接 | `fatal("Failed to connect to PostgreSQL after 10 retries")` | MUST 输出；触发告警 |
| `ERROR` | 单请求失败但系统整体可用：5xx 响应、DB 事务回滚、第三方集成 fatal 错误 | `error("Failed to send invite email: SMTP timeout", extra={"invite_id":...})` | MUST 输出；按错误码 severity=FATAL 触发告警 |
| `WARN` | 可恢复异常、限流命中（429）、刷新 token 复用检测、慢查询阈值超 | `warn("Slow query > 500ms", extra={"sql": "...", "duration_ms": 520})` | MUST 输出 |
| `INFO` | 正常业务动作：登录成功、创建资源、报名成功、入社申请通过（对应审计落库） | `info("User enrolled exam", extra={"user_id": ..., "exam_id": ..., "trace_id": ...})` | MUST 输出 |
| `DEBUG` | 细粒度诊断：函数入参/返回、SQL explain、缓存命中 | `debug("Cache hit for exam list", extra={"key": ...})` | 生产默认 **MUST NOT** 输出（`LOG_LEVEL=INFO`） |

**统一日志额外字段（每条日志 SHOULD 带，INFO 以上 MUST 带）**：
- `trace_id`：请求唯一 ID（`request.state.request_id`，中间件生成）
- `user_id`：已登录用户 ID；匿名 `-1`
- `domain`：资源域（users/auth/exams …）或 `core`/`middleware`
- `duration_ms`：耗时（若适用）
- `error_code`：错误响应的 code（若失败）
- 禁止：`password` / `token` / `phone` / `email` / `totp` 明文（对齐 LOG-01）

#### 5.2.2 异常统一处理（`app/core/exceptions.py` + `error_codes.py` + middleware）

三层异常 MUST 按此分类：
| 异常基类 | 用途 | HTTP status | 示例 |
|---|---|---|---|
| `AppException(Exception)` | 业务可控异常（用户不存在、权限不足、考试已截止）| 4xx / 5xx 自定义 | `raise AppException(ErrorCode.E_EXAM_005_CLOSED)` → 400 |
| `AuthException(AppException)` | 认证异常子类 | 401 / 403 | `raise AuthException(ErrorCode.E_AUTH_002_TOKEN_EXPIRED)` |
| 非预期异常（ValueError、KeyError、DB IntegrityError 等）| 非显式抛出 | 500 | 捕获 → `exception()` 日志 → 返回通用 `E_SYS_000_INTERNAL`，不泄露详情 |

**异常处理顺序（FastAPI exception handlers 注册顺序 = 优先级）**：
1. `AppException` handler → 走注册表 Envelope
2. `RequestValidationError`（Pydantic）handler → code=`E_VAL_*` 系列（Val 前缀模块），返回字段级错误细节
3. Starlette `HTTPException` → 兼容 BFF / 第三方，但 SHOULD 逐步收敛到 `AppException`
4. 兜底 `Exception` handler → 500 `E_SYS_000_INTERNAL`，trace_id 附日志；不返回堆栈

#### 5.2.3 中间件顺序（`main.py` `add_middleware(...)` 注册顺序 MUST 严格）

```
请求进入 → ← 响应返回
    │
    1. RequestIdMiddleware（注入 trace_id；最外层，最先入最后出）
    2. CORSMiddleware（其次，OPTIONS 必须短路返回）
    3. ApiUsageMiddleware（埋点，入/出都触发）
    4. RateLimitMiddleware（认证前限流：匿名 IP 级）
    5. RBACPreloadMiddleware（预加载用户权限到 request.state；鉴权层通过 Depends require_permission 使用）
    6. ErrorHandlerMiddleware（兜底异常转 Envelope；最内层前半，最后出后半）
    └── FastAPI route handler（Depends 注入 current_user、权限校验）
```

#### 5.2.4 性能实践条目

| 项 | 实践 | 阈值 / 参考 |
|---|---|---|
| DB N+1 查询 | services 层 MUST 使用 `selectinload` / `joinedload`；list 接口不得 for 循环再查 | `query.count()` 走单独 count；分页接口 MUST 一次性取所有关联 |
| 慢查询阈值 | 超过 **500ms** WARN 日志；超过 **2s** ERROR + 告警；**MUST** 补索引 | `pg_stat_statements` 定期审计 top 10 slow |
| 大文件上传 | 图片/附件 MUST 经后端流式 → 对象存储（本地/S3）；**MUST NOT** 存 DB | 单次 ≤ 10MB（默认），业务可放宽但 MUST 有限流 |
| 缓存策略 | LLM 对话上下文、用户权限列表（少变）SHOULD 用 Redis TTL 缓存；**MUST NOT** 缓存考试试题（防作弊） | 默认 TTL 300s；写操作 MUST invalidate |
| 避免 N+1 HTTP | BFF/后端调用第三方（OAuth、SMTP、LLM）SHOULD 批量 + 超时；重试带指数退避 | 超时默认 15s；SSE/Streaming 可放宽 60s |
| 分页强制 | 所有列表接口 **MUST** 分页（见 §3.2.2），禁止 `return db.query(Post).all()` 全量返回 | |

### 5.3 约束（RFC2119 分层）

**MUST（铁律红线）：**
1. **日志分级 + 必需字段（INFO 以上）MUST 对齐 §5.2.1 表**；`trace_id`、`user_id`、`domain` **MUST** 存在；**MUST NOT** 记录 token/密码/手机/邮箱/TOTP 明文（LOG-01）。
2. **异常分类 MUST 用三层基类（AppException/AuthException/兜底）**；**MUST NOT** api/services 层 `return JSONResponse(status_code=400, content={"error":"..."})` 裸返回（违反 Envelope 规范）。
3. **Pydantic 校验失败 MUST 返回错误码 `E_VAL_*` 系列**（字段级细节 data.details）；**MUST NOT** 返回默认 FastAPI `{"detail":[...]}` 非标准结构。
4. **中间件顺序 MUST 严格 §5.2.3 表**；`RequestIdMiddleware` 最外、`ErrorHandlerMiddleware` 最内；**MUST NOT** 调换（否则 429 限流无 trace_id、兜底异常无 CORS 头）。
5. **全量返回禁止**：列表接口 **MUST** 分页；**MUST NOT** `return query.all()` 全量（数据上万 = DB 压力 + 响应超时）。
6. **慢查询阈值 MUST 有日志 + 告警**；> 500ms WARN、> 2s ERROR；**MUST NOT** 认为「我本地没慢」就忽略。
7. **大文件上传 MUST 不进 DB**；**MUST** 对象存储 + DB 只存引用（key、size、content_type、owner_id）。
8. **兜底异常 MUST 返回通用 E_SYS_000_INTERNAL**；**MUST NOT** 用户看到堆栈/内部 SQL/PG 错误文（对齐 BackDoc-02-Sec §2）。

**MUST NOT（禁止事项）：**
1. **MUST NOT** 生产默认 `LOG_LEVEL=DEBUG`；DEBUG 级输出 MUST 仅本地开发（`DEBUG=true`）启用。
2. **MUST NOT** 用裸 `print()` 输出任何业务信息；**MUST** `logging.getLogger(__name__)` 统一。
3. **MUST NOT** services 层捕获 `Exception: pass` 静默吞异常；至少 MUST `exception("Caught and swallowed", exc_info=True)` 日志保留诊断。
4. **MUST NOT** 中间件里写业务 `commit()` / 权限判断；中间件 **MUST** 只读 request.state，不写 DB。
5. **MUST NOT** 缓存考试试题 / 答案 / TOTP seed / refresh token 等高敏数据；缓存 **MUST** 白名单制，默认不缓存。
6. **MUST NOT** list 接口的分页 `count(*)` 走 ORM `len(query.all())`（全表拉回内存）；**MUST** `func.count()` SQL 层 count。
7. **MUST NOT** `joinedload` 套 3 层以上大 join 造成笛卡尔积；按需拆 `selectinload` 或多次查询 + 缓存。

**SHOULD（建议事项）：**
1. **SHOULD** 日志 JSON 结构化（`python-json-logger`）；配合 Loki/ELK 按 trace_id、domain、user_id 聚合检索。
2. **SHOULD** 每个 ErrorCode severity ≥ ERROR 的异常触发 Slack/飞书告警到后端频道；FATAL MUST paging oncall。
3. **SHOULD** 数据库层引入 `sqlalchemy-echo` 开发期开启，自动扫描 N+1（每 API > 5 条 SQL 就 review）。
4. **SHOULD** 分页接口提供「可扩展字段投影」（`fields=id,title,created_at`）减少 IO；大字段（content 正文）默认列表不返回，详情接口才返回。
5. **SHOULD** 性能问题修复 MUST 配套 benchmark（`pytest-benchmark`）；前后对比 ≤ 原时间 20% 退化。

**MAY（可选配置）：**
1. **MAY** 引入 `opentelemetry` 分布式追踪（trace_id 已在中间件注入，接入成本低）；MVP 可简化为日志 + Prometheus metrics（/metrics）。
2. **MAY** 对象存储兼容层（S3/本地目录/七牛云/COS）抽象到 `app/core/storage.py`；MVP 先本地目录，完整版切 S3。

### 5.4 自检 CheckList

- [ ] 日志：INFO+ 三字段（trace_id/user_id/domain）齐全；LOG-01 0 明文敏感
- [ ] 异常：三层基类全覆盖；Pydantic `E_VAL_*` 返回；0 处裸 JSONResponse
- [ ] 中间件顺序：§5.2.3 顺序 1→6 正确；CORS 头 + trace_id 全响应携带
- [ ] 性能：列表接口 100% 分页；0 处 `query.all()` 全量；N+1 review 通过
- [ ] 慢查询：> 500ms WARN 日志存在；> 2s ERROR + 告警配置
- [ ] 大文件：不存 DB；对象存储 + DB 仅存引用；≤ 10MB（默认）
- [ ] 兜底：5xx 通用错误码 + trace_id；0 处堆栈/SQL 泄露 UI

---

## 6. 变更门禁 + Pre-commit 必查清单（Reference 型文档强制尾章）

> 每次提交涉及 DDD 分层、测试、API 规范、依赖、Alembic、配置、日志、异常、中间件、性能的任何变更前，提交人 MUST 逐项自查并在 PR 描述打钩；CR 审核人 MUST 核对并在未打钩时打回。

### §6.1 通用门禁（所有后端变更适用）

- [ ] 变更是否影响 §1–§5 任一 MUST/MUST NOT 约束？若是本节约束文字 MUST 已同步更新
- [ ] `make ci` 后端子仓：`make lint + make typecheck + make test + make docs-health + make gen-doc-facts` 全绿
- [ ] 6 行元数据头：版本号、变更日期已同步更新（若改动文档本身）
- [ ] 跨仓同步：若改动 `/api/v1` 契约/枚举/字段，前端 BFF 与移动端 ApiClient MUST 同步 PR 已关联 / 同时提交
- [ ] 版本三源 + Alembic：`make gen-doc-facts` 0 diff（RootEngConv §2 上位）

### §6.2 DDD 分层门禁（§1 相关）

- [ ] 六层职责边界：grep 检查 0 跨层违规
- [ ] 模块目录 6 文件齐全或按阈值拆分；router 汇总 include_router 前缀 `/api/v1/{domain}` 正确
- [ ] Response DTO：独立声明；未从 ORM 继承；字段白名单无敏感
- [ ] Depends 公共函数仅 `app/api/deps.py` 定义；0 模块重复副本
- [ ] 跨模块调用：仅 services 公开接口；0 跨模块 import repositories/models

### §6.3 测试门禁（§2 相关）

- [ ] 三层职责分离：Unit 0 真 PG；E2E 0 mock services/repositories
- [ ] 覆盖率：总体 ≥ 80%、core/auth/users ≥ 90%；低于阈值有补测或说明
- [ ] 写路由 3 角色 case（anon/member/admin）齐全；`migrated_db` roundtrip 测试通过
- [ ] 测试命名 `test_{动词}_{预期}_{条件}`；无 skip 无 issue 追踪
- [ ] 夹具独立：任意单 test 重跑通过；0 A→B 顺序依赖

### §6.4 API 规范门禁（§3 相关）

- [ ] Envelope 统一：0 处裸 JSON；全部走 `APIResponse.success/error`
- [ ] 错误码注册表：E_前缀与模块对应；0 处裸字符串 `code="E_..."`
- [ ] HTTP status × success 语义一致；2xx→true / 4xx/5xx→false
- [ ] 分页七字段齐全；`page_size ≤ 100`；`sort_by` Literal 白名单
- [ ] 时间 UTC iso；字段全 snake_case；错误码 JSON 导出（供前端契约）已同步

### §6.5 依赖 / Alembic / 配置门禁（§4 相关）

- [ ] 依赖分层：0 dev 进 core；`uv.lock` 已同步
- [ ] Alembic：1 head + 可回滚 + Domain 三行头 + `alembic check` 0 diff
- [ ] 配置：SecretStr 高敏；`.env.example` 与 Settings 1:1；功能开关默认保守
- [ ] `.env`：.gitignore 生效；gitleaks 无告警
- [ ] 数据迁移脚本：独立 `scripts/migrate_*.py`；不混 schema migration

### §6.6 日志 / 异常 / 中间件 / 性能门禁（§5 相关）

- [ ] 日志：INFO+ 三字段齐全；LOG-01 0 明文敏感；生产 LOG_LEVEL=INFO
- [ ] 异常：三层基类 + Pydantic `E_VAL_*`；0 裸 JSONResponse；兜底 5xx 通用码
- [ ] 中间件顺序 1→6 正确；CORS 头 + trace_id 全响应携带
- [ ] 性能：列表 100% 分页；0 `query.all()`；N+1 review；慢查询日志 + 告警
- [ ] 大文件：对象存储 + DB 引用；不存 DB；大小限制有效

---

> ↩ **返回后端架构总览**：[BackDoc-01-Arch.md](BackDoc-01-Arch.md) · **后端安全红线**：[BackDoc-02-Sec.md](BackDoc-02-Sec.md) · **模块契约**：[BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md) · **跨仓通用约定**：[RootDoc-EngConv.md](../../../docs/RootDoc-EngConv.md) · **命名门禁**：[RootDoc-ModuleMap.md](../../../docs/RootDoc-ModuleMap.md)
