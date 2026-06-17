# CONVENTIONS.md

本项目的编码规范、目录组织与通用约定。**所有贡献者（含 AI Agent）在写代码前必须先读本文档**。
项目级扩展约定（如何加模块、中心注册点、Alembic 迁移）见 `AGENTS.md`；项目定位与硬性禁止项见 `CLAUDE.md`。

> 文档优先级：场景内具体指令 > `AGENTS.md` > `CLAUDE.md` > 本文件 > 通用工作流。

---

## 1. 项目结构总览

```
app/
├── api/v1/        # 路由层（每个资源一个文件，在 v1/__init__.py 汇总注册）
├── core/          # 基础设施：config / loguru_logger / security / redis_client
│   ├── exceptions/  # 业务异常基类 + 全局处理器 + ExceptionHandlerMiddleware
│   ├── cache/       # 可降级通用缓存
│   └── rate_limit/  # 可降级限流
├── middleware/    # monitoring / rate_limit / rbac（权限校验依赖）
├── models/        # ORM 模型（在 models/__init__.py 汇总导出）
├── repositories/  # 数据访问层（只做 CRUD，不含业务规则）
├── schemas/       # Pydantic 入/出参
├── services/      # 业务逻辑层（编排 repo + 校验 + 业务规则）
├── utils/         # 跨 service/repo 的纯工具函数
├── database.py    # 引擎 + get_db / get_session / ensure_database_exists
├── dependencies.py
└── main.py        # 入口：中间件注册、异常处理器、lifespan
tests/             # 镜像 app/ 结构，子包必须有 __init__.py
alembic/           # 生产 schema 迁移（开发/测试不用）
```

### 分层调用规则（铁律）

```
api (路由)  →  service (业务)  →  repository (数据)  →  model (ORM)
   │
   └─ 只通过 Depends 注入依赖；不跨层调用
```

- **禁止跨层**：路由不直接调 repo；service 不直接发 SQL，必须经 repo。
- **service 间调用**：允许（组合业务），但**只能通过构造函数注入**依赖的 service，禁止方法内部 `import` 另一个 service（保证可测试性）。
- **不跨级反向依赖**：repo/model/core 不允许反向 import service/api。

### 文件放置规则（公共逻辑去哪）

| 类型 | 放置位置 |
|---|---|
| 多个 service/repo 共用的纯函数（金额计算、格式化、状态转换） | `app/utils/` |
| 与框架/基础设施强相关（缓存、限流、认证、日志） | `app/core/` |
| 只被一个 service 用的辅助逻辑 | 留在该 service 文件内的私有函数（带 `_` 前缀），不外抽 |
| ORM 模型 | `app/models/<name>.py`，必须在 `models/__init__.py` 登记 |
| 业务异常 | 继承 `BaseAppException`，在 `exceptions/__init__.py` 登记 |

---

## 2. 命名规范

| 对象 | 规范 | 示例 |
|---|---|---|
| 文件 | `snake_case.py`；repo 文件带 `_repo` 后缀，service 带 `_service` 后缀 | `user_repo.py`, `auth_service.py` |
| 类 | `PascalCase`；ORM 模型用单数 | `User`, `RefreshToken` |
| 函数/方法 | `snake_case`；私有以 `_` 开头 | `_hash_password` |
| 常量 | `UPPER_SNAKE_CASE` | `DEFAULT_PAGE_SIZE` |
| 路由前缀 | 小写复数，`/` 分隔 | `/users`, `/rbac/permissions` |
| 数据库表 | `snake_case`，复数 | `users`, `refresh_tokens` |
| 配置项 | `UPPER_SNAKE_CASE`（`.env` 与 `Settings` 字段同名） | `SECRET_KEY`, `DB_AUTO_CREATE` |

---

## 3. Python 与异步约定

- **全异步**：所有 IO（DB、Redis、HTTP）一律 `async def`；禁止在异步路径里调用阻塞 IO。
- **Python 版本**：跟随 `requirements.txt`，类型注解必填（公共函数签名、Pydantic 字段）。
- **DB 会话**：
  - 路由内：`Depends(get_db)`。
  - 路由外（worker/脚本/后台任务）：`async with get_session() as db:`。
  - **两者都不自动提交**，必须显式 `await db.commit()`；出异常自动回滚。
- **时间列**：ORM 时间列一律带时区，使用 `DateTime = _DateTime(timezone=True)` 别名模式（参考现有 models）。
- **日志**：`from app.core.loguru_logger import get_logger`；**禁止 `print`、禁止直接配置 loguru handler**。

---

## 4. 代码质量红线

### 4.1 文件大小

- 单个 `.py` 文件超过 **~300 行**时必须停下来评估拆分（按职责拆函数/类/文件）。
- 非强制阈值，但是「这文件是不是干了太多事」的信号。

### 4.2 函数与职责

- **单一职责**：一个 service 只管一个业务域；一个函数只做一件事。禁止「订单+支付+物流」塞进一个 `order_service.py`。
- **提前返回降嵌套**：嵌套控制在 **3 层**以内，超过考虑重构控制流。
- **函数长度**：明显超过一屏（约 50–80 行逻辑代码）或包含多个处理阶段时，按语义拆辅助函数。
- **避免布尔参数控制多模式**：必要时改用枚举/策略对象/独立函数。

### 4.3 DRY 与抽象

- **三次法则**：同一段逻辑在 3 处出现，必须抽公共函数；1–2 处直接写，**不要预先抽象**。
- 出现真实重复才复用；不要因为两段代码暂时相似就过早抽象。

### 4.4 圈复杂度

- 单函数圈复杂度建议 ≤ **10**；超过考虑用早返回、查表、策略对象拆分。
- 避免深度嵌套的 `if/elif` 链，优先改写为「条件 → 动作」的映射。

---

## 5. 错误处理约定

- **业务错误**：抛 `BaseAppException` 子类（`app/core/exceptions/base_exceptions.py`），由全局处理器统一映射状态码。
- **禁止**：在路由里 `try/except` 吞掉业务异常再返回自定义格式——绕过统一异常处理体系。
- **禁止空 catch / 静默吞错**：必须记录或向上抛；错误信息保留上下文但**不得泄露敏感信息**（密钥、令牌、密码）。
- **系统边界校验**：外部输入（HTTP/文件/外部 API）必须校验；内部代码信任类型，不重复校验。
- **中间件短路**：中间件里要短路就 `return JSONResponse(...)`，**禁止 `raise HTTPException`**（异常处理器只覆盖路由层，中间件异常由最外层 `ExceptionHandlerMiddleware` 兜底）。

---

## 6. 安全约定

- **禁止硬编码**密钥、令牌、密码、生产凭证；统一从配置或环境变量读取。
- **密码**：使用 `app/core/security.py` 的哈希函数，禁止自实现加密。
- **权限**：用依赖 `require_permission / require_role / require_superuser`（`app/middleware/rbac.py`），**禁止用装饰器**。
- **SQL**：使用 SQLAlchemy 参数化查询，禁止字符串拼接 SQL 或命令。
- **输入校验**：Pydantic schema 在路由层校验；ORM 层信任 schema 已校验。
- **日志**：禁止记录密码、token、个人敏感信息。

---

## 7. 配置约定

- 所有配置项定义在 `app/core/config.py` 的 `Settings` 类。
- **新增配置字段必须同步 `.env.example`**，否则他人无法知道配置项。
- 环境分层：
  - `.env.development`（开发，`DB_AUTO_CREATE=True`）
  - `.env.test`（测试，`DB_AUTO_CREATE=True`）
  - `.env`（生产，`DB_AUTO_CREATE=False`，走 alembic）
- **`SECRET_KEY` 必须从环境变量设置，禁止占位值**。

---

## 8. 测试约定

- **目录结构**：`tests/` 镜像 `app/` 子包结构；每个子包必须有 `__init__.py`（见 `tests/README.md`）。
- **命名**：测试文件 `test_*.py`，测试函数 `test_*`。
- **异步**：`pytest.ini` 段名必须是 `[pytest]`，`asyncio_mode=auto`，异步测试直接 `async def`，**不要** `@pytest.mark.asyncio`。
- **运行**：`python -m pytest`。
- **覆盖要求**：新增/修改业务逻辑必须补测试；至少覆盖正向、反向、边界三类路径。

---

## 9. Git 与提交

- **提交格式**：`<type>(<scope>): <subject>`，type：`feat / fix / refactor / chore / docs / test`。
- **不主动 commit / push**，除非用户明确要求。
- **禁止提交**：`*.db`、`logs/`、`.env*`（除 `.env.example`）。
- **侵入性操作**（删文件、改公共接口、改数据库结构）**先说明范围再做**。

---

## 10. 数据库迁移约定（摘要）

> 完整规则与爆炸场景见 `AGENTS.md` 的「Alembic 迁移管理」章节。

- **铁律**：`create_all` 与 `alembic` **绝不在同一库同时用**。
  - 开发/测试环境：`DB_AUTO_CREATE=True`，**不跑 alembic**。
  - 生产环境：`DB_AUTO_CREATE=False`，走 `alembic upgrade head`。
- **改模型流程**：改 model → 登记 `models/__init__.py` → `alembic revision --autogenerate -m "..."` → 检查 upgrade() → 确认单一 head。
- **禁止**修改 baseline 或已有迁移文件（历史事实不可改）。
- **专属库**：本项目用 PG 库 `domefff`，**勿与其它项目共用一个库**。

---

## 11. 禁止事项汇总（来自 CLAUDE.md）

- 禁止前端渲染：Jinja2 / StaticFiles / HTMLResponse。
- 禁止 sqlite 作生产库（仅 PostgreSQL）。
- 禁止直接 `print` 或直接配置 loguru handler。
- 禁止提交 `*.db`、`logs/`、`.env`。
- 禁止 `AUTH_ENABLED=False` 用于生产（`DEBUG=False` 时会拒绝启动）。

---

## 12. 检查清单（提交前自查）

- [ ] 新代码风格与周围代码一致（async、命名、错误处理）？
- [ ] 改动半径最小？没有顺手重构无关模块？
- [ ] 文件未超 ~300 行？函数嵌套 ≤ 3 层？圈复杂度合理？
- [ ] 公共逻辑已抽到 `utils/` 或 `core/`？没有 1–2 处就过早抽象？
- [ ] 新增 ORM 模型/异常/中间件/配置 已在中心注册点登记？
- [ ] 业务错误抛 `BaseAppException` 子类？没有在路由吞异常？
- [ ] 日志用 `get_logger`？没有 `print`？
- [ ] 测试已补？`python -m pytest` 通过？
- [ ] 新增配置项已同步 `.env.example`？
- [ ] 改了公共签名已扫调用点，并用默认值保持兼容？
