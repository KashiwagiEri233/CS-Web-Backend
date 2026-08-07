# AGENTS.md

AI Agent 工作约定，作用域内优先于通用行为。配合 `CLAUDE.md`（项目定位、配置、硬性禁止项）一起读。
本文件聚焦**如何扩展项目而不制造冗余/散落**——这些约定在项目演进中不变。

## 工作原则
- **最小改动半径**：只改实现需求所必需的内容；先找可复用的现有实现。
- **保持分层**：`api → service → repository → model`，不跨层调用。
- **风格一致**：新代码要像旧代码（async、命名、错误处理）。
- **改完即验**：跑 `python -m pytest`；改了模型/公共签名先扫调用点，公共签名加参用默认值保持兼容。
- **侵入性操作先确认**：删文件、改公共接口、改数据库结构，先说明范围再做。
- **避免魔法值**：在代码中避免使用魔法值（如 `123`、`456`），而应使用常量或配置项,尽量使用显式声明的常量，如 `MY_CONST = 123`,尽量使用枚举类型。
- **文档**：在遇到熟悉代码的过程中请先查看.docs文件是否有相关文档。
- **注释**：在代码中添加必要的注释，包括函数、类、模块等。
- 不主动 commit / push，除非明确要求。

### 代码组织纪律（普适，不限功能大小）

- **DRY 三次法则**：同一段逻辑在 3 处出现，必须抽成公共函数/方法；只有 1-2 处时直接写，不要预先抽象。
- **公共逻辑放置规则**：
  - 多个 service/repo 共用的纯函数 → `app/utils/`（如金额计算、格式化、状态转换）。
  - 与框架/基础设施强相关（缓存、限流、认证） → `app/core/`。
  - 只被一个 service 用的辅助逻辑 → 留在该 service 文件内的私有函数，不外抽。
- **文件大小红线**：单个 `.py` 文件超过 ~300 行时必须评估拆分（按职责拆函数/类/文件），不是强制阈值，但是必须停下来想"这个文件是不是干了太多事"的信号。
- **单一职责**：一个 service 只管一个业务域；一个函数只做一件事。不要把订单+支付+物流塞进一个 `order_service.py`。
- **service 之间调用规则**：service 可以调用其他 service（组合业务），但只能通过构造函数注入的依赖，不要在方法内部 import 另一个 service（保持可测试性）。

## 中心注册点（加东西必须在这里登记，否则不生效或散落）

| 新增 | 放哪 | 必须登记到 |
|---|---|---|
| API 资源 | `app/api/v1/<name>.py`（`router = APIRouter()`） | `app/api/v1/__init__.py` → `api_router.include_router(router, prefix=..., tags=[...])` |
| ORM 模型 | `app/models/<name>.py` | `app/models/__init__.py`：import + 加入 `__all__`（否则 alembic autogenerate 看不到） |
| 业务异常 | 继承 `BaseAppException`（`app/core/exceptions/base_exceptions.py`） | `app/core/exceptions/__init__.py` 的 `__all__`；若需专属处理逻辑，再在 `setup_exception_handlers` 注册 |
| 错误码 | `ErrorCode` 命名空间（`app/core/exceptions/error_codes.py`） | 见下方「错误码（ErrorCode 注册表）」——禁止裸字符串 |
| 中间件 | `app/middleware/<name>.py` | `app/main.py` 按顺序 `add_middleware`（见下方顺序约定） |
| 配置项 | `app/core/config.py` 的 `Settings` | 同步加到 `.env.example` |
| 迁移 | `alembic revision --autogenerate -m "..."`（改完模型后） | 提交前确认只有单一 head |
| 启动/关闭任务 | `@register_startup` / `@register_shutdown` 装饰器（`app/core/lifecycle/`） | 注册点模块须在 `app/core/lifecycle/__init__.py` 的 `_import_registrants()` 中 import 触发登记；详见 `tools/docs/BackDoc-Infra.md` |
| 测试 | `tools/tests/<镜像 app 的子包>/test_*.py` | 子包需有 `__init__.py`（见 `tools/tests/README.md`） |
| 模块文档 | 系统级 → `tools/docs/BackDoc-02-Sec.md`/`tools/docs/BackDoc-Infra.md`；业务级 → `tools/docs/BackDoc-Mods.md` | 登记到 `tools/docs/README.md` 索引表；含「接口」节（见 `tools/docs/README.md` 的分类约定与模板） |

## 加一个 API 资源（标准配方）

> 加功能前先评估：这是单一资源还是多模块组合？如果是后者（如"订单系统"含订单/订单项/支付），先按业务域拆分 service 和 repo，再对每个子资源分别走下面的配方。公共能力（枚举、常量、工具函数）先建，再逐模块实现。

1. **模型** `app/models/<x>.py` → 在 `app/models/__init__.py` import 并加进 `__all__`。
2. **schema** `app/schemas/<x>.py`：Pydantic v2（`model_config = ConfigDict(...)`，需从 ORM 转换时加 `from_attributes=True`）。
3. **repository** `app/repositories/<x>_repo.py`：构造函数收 `db: AsyncSession`，只做数据访问。
4. **service** `app/services/<x>_service.py`：构造函数收 `db`，写业务逻辑；不依赖 `Request`（这样 worker/脚本也能复用）。
5. **路由** `app/api/v1/<x>.py`：端点用 `Depends(get_db)`，鉴权用 `Depends(require_permission("<res>","<act>"))`。
6. 在 `app/api/v1/__init__.py` 注册 router。
7. **建表/迁移**：按下方「Alembic 迁移管理」执行。
8. 在 `tools/tests/` 对应子包补测试。

## 错误码（ErrorCode 注册表）

错误码是客户端对照的契约，必须**单一事实源**。所有错误码常量集中定义在
`app/core/exceptions/error_codes.py` 的 `ErrorCode` 类里，**禁止在异常类、handler、
service、路由中写裸字符串**（如 `error_code="USER_NOT_FOUND"`）。

### 组织方式：类命名空间

`ErrorCode` 用嵌套类形成命名空间，访问形式固定为 `ErrorCode.<Namespace>.<NAME>`：

```python
from app.core.exceptions import ErrorCode

raise AuthenticationException(error_code=ErrorCode.Auth.INVALID_CREDENTIALS)
```

当前命名空间**按异常类层次划分**（`Auth` / `Authorization` / `Validation` /
`NotFound` / `Conflict` / `Database` / `ExternalService` / `RateLimit` /
`Business` / `System`），因为现阶段所有异常都集中在 core。

### 加一个错误码

1. 在 `error_codes.py` 找到对应命名空间类，加 `XXX = "XXX"`（常量名 = 字符串值，便于全局检索）。
2. 在抛出处引用 `ErrorCode.<Namespace>.XXX`，不要写字面量。
3. 若该错误码对应 HTTP 异常的状态码兜底，登记到 `exception_handlers.py` 的 `_HTTP_ERROR_CODES`（同样用常量，不写字面量）。
4. 仅 `response_models.py` 里 `json_schema_extra` 的示例 JSON 与 `f"HTTP_{status}"` 动态模板属例外，可保留字面量（前者是文档示例，后者是动态命名）。

### 第二步预留：业务模块自治（演进方向，暂不执行）

> ℹ️ 变更记录/待办条目已迁移至 `docs/项目演变历史.md` / `docs/项目待办事项.md`。

## Alembic 迁移管理（Schema 唯一来源）

### 铁律：全环境只用 Alembic，禁止 `create_all`

| 环境 | 建表方式 | 说明 |
|---|---|---|
| 开发 / 测试 / 生产 | **仅** `alembic upgrade head` | 启动任务在 `DB_AUTO_MIGRATE=True` 时自动 upgrade；`False` 时只校验版本 |
| 历史字段 `DB_AUTO_CREATE` | **已废弃** | 启动路径忽略；即使 True 也不再 `Base.metadata.create_all` |

- **禁止**在应用代码 / 脚本 / 测试中调用 `Base.metadata.create_all`。
- 改模型必须生成迁移文件；空库靠迁移链从 baseline 建到 head。
- 若旧开发库曾被 `create_all` 建过、无 `alembic_version`：先 `alembic stamp head`（结构已对齐时）或 drop 库后靠 upgrade 重建。

### 改模型后的正确流程（增量迁移）

1. 改 `app/models/<x>.py`，在 `app/models/__init__.py` 登记。
2. **不要**改 baseline 或已有迁移文件（历史事实）。
3. 生成增量迁移：
   ```bash
   alembic revision --autogenerate -m "add <table>_<变更摘要>"
   ```
4. **检查**生成的 `upgrade()` / `downgrade()`，确认只含本次变更。
5. 提交前确认单一 head：
   ```bash
   alembic heads   # 必须只输出一行
   alembic history
   ```
6. 应用：`alembic upgrade head`（或依赖启动时 `DB_AUTO_MIGRATE=True`）。

### 常见问题与规避

| 症状 | 原因 | 解法 |
|---|---|---|
| upgrade 报「表已存在」 | 旧库由 create_all 建过、无版本表 | `alembic stamp head` 或 drop 库重建后 upgrade |
| autogenerate 空迁移 | 模型与 DB 已一致 | 删掉空文件 |
| 多 head | 分支迁移 | `alembic merge -m "merge heads" <h1> <h2>` |
| 启动报版本不一致 | `DB_AUTO_MIGRATE=False` 且未先 upgrade | 先 `alembic upgrade head` |

### 开发环境快速重置

```bash
psql -U postgres -c "DROP DATABASE IF EXISTS domefff;"
psql -U postgres -c "CREATE DATABASE domefff;"
# 重启服务：DB_AUTO_MIGRATE=True 时 lifespan 会 alembic upgrade head
python run.py --env 1
# 或手动：alembic upgrade head
```

### 迁移文件命名约定

- 文件名：`<revision>_<动词>_<表名>.py`（如 `a1b2c3d4e5f6_add_refresh_tokens.py`）
- 一个迁移只做一件事（加表/加列/改列/加索引），不要把多个不相关变更塞进同一个迁移
- `down_revision` 必须指向当前 head，不要指向历史节点（会造成多 head）

## 不变量（贯穿全项目，勿打破）
- **DB 会话 / 事务**：路由用 `Depends(get_db)`；路由外用 `async with get_session() as db:`。**Repository 只 flush，不 commit**；**Service 显式 `await db.commit()`**（禁止 repo 内 commit，避免跨 repo 半提交）。
- **时间列**：模型时间列一律带时区——文件内用 `DateTime = _DateTime(timezone=True)` 别名模式（见现有 models）。
- **权限**：业务 API 用 `require_permission("<res>","<act>")`（`app/middleware/rbac.py`），不要用装饰器；超级用户由 `PermissionChecker` 旁路。不要默认整页 `get_current_superuser` 替代细粒度权限。
- **中间件抛错**：中间件里要短路就 `return JSONResponse(...)`，**不要 `raise HTTPException`**（注册的处理器只覆盖路由层；中间件异常由最外层 `ExceptionHandlerMiddleware` 兜底映射状态码）。
- **中间件顺序**（`main.py`，后 `add` 的在外层）：CORS → 异常处理 → 安全头 → 日志 → 指标 → 限流 → 认证限流。
- **异常**：业务错误抛 `BaseAppException` 子类，别在路由里 `try/except` 吞掉再返回自定义格式；错误码一律用 `ErrorCode.*` 常量，禁止裸字符串（见「错误码（ErrorCode 注册表）」）。
- **日志**：`from app.core.loguru_logger import get_logger`；禁止 `print`、禁止直接配置 loguru handler。
- **Redis 可降级**：限流/缓存把 Redis 当增强项——未配置走内存、故障自动降级；不要把它写成强依赖。
- **启动逻辑走注册表**：启动 / 关闭的初始化用 `@register_startup` / `@register_shutdown`（`app/core/lifecycle/`）自注册，`main.py` 的 `lifespan` 只调 `run_startup()` / `run_shutdown()`。**禁止**把启动逻辑硬编码回 `main.py`；只有应用级一次性展示（横幅、AUTH_ENABLED 告警）可直接留在 `lifespan` 内。

## Git
需要 commit 时：`<type>(<scope>): <subject>`（type：feat/fix/refactor/chore/docs/test）。
