# AGENTS.md

AI Agent 工作约定，作用域内优先于通用行为。配合 `CLAUDE.md`（项目定位、配置、硬性禁止项）一起读。
本文件聚焦**如何扩展项目而不制造冗余/散落**——这些约定在项目演进中不变。

## 工作原则
- **最小改动半径**：只改实现需求所必需的内容；先找可复用的现有实现。
- **保持分层**：`api → service → repository → model`，不跨层调用。
- **风格一致**：新代码要像旧代码（async、命名、错误处理）。
- **改完即验**：跑 `python -m pytest`；改了模型/公共签名先扫调用点，公共签名加参用默认值保持兼容。
- **侵入性操作先确认**：删文件、改公共接口、改数据库结构，先说明范围再做。
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
| ORM 模型 | `app/models/<name>.py` | `app/models/__init__.py`：import + 加入 `__all__`（否则 `create_all` 与 alembic autogenerate 都看不到） |
| 业务异常 | 继承 `BaseAppException`（`app/core/exceptions/base_exceptions.py`） | `app/core/exceptions/__init__.py` 的 `__all__`；若需专属处理逻辑，再在 `setup_exception_handlers` 注册 |
| 错误码 | `ErrorCode` 命名空间（`app/core/exceptions/error_codes.py`） | 见下方「错误码（ErrorCode 注册表）」——禁止裸字符串 |
| 中间件 | `app/middleware/<name>.py` | `app/main.py` 按顺序 `add_middleware`（见下方顺序约定） |
| 配置项 | `app/core/config.py` 的 `Settings` | 同步加到 `.env.example` |
| 迁移 | `alembic revision --autogenerate -m "..."`（改完模型后） | 提交前确认只有单一 head |
| 测试 | `tests/<镜像 app 的子包>/test_*.py` | 子包需有 `__init__.py`（见 `tests/README.md`） |
| 模块文档 | 系统级 → `docs/system/<x>.md`；业务级 → `docs/modules/<x>.md` | 登记到 `docs/README.md` 索引表；含「接口」节（见 `docs/README.md` 的分类约定与模板） |

## 加一个 API 资源（标准配方）

> 加功能前先评估：这是单一资源还是多模块组合？如果是后者（如"订单系统"含订单/订单项/支付），先按业务域拆分 service 和 repo，再对每个子资源分别走下面的配方。公共能力（枚举、常量、工具函数）先建，再逐模块实现。

1. **模型** `app/models/<x>.py` → 在 `app/models/__init__.py` import 并加进 `__all__`。
2. **schema** `app/schemas/<x>.py`：Pydantic v2（`model_config = ConfigDict(...)`，需从 ORM 转换时加 `from_attributes=True`）。
3. **repository** `app/repositories/<x>_repo.py`：构造函数收 `db: AsyncSession`，只做数据访问。
4. **service** `app/services/<x>_service.py`：构造函数收 `db`，写业务逻辑；不依赖 `Request`（这样 worker/脚本也能复用）。
5. **路由** `app/api/v1/<x>.py`：端点用 `Depends(get_db)`，鉴权用 `Depends(require_permission("<res>","<act>"))`。
6. 在 `app/api/v1/__init__.py` 注册 router。
7. **建表/迁移**：按下方「Alembic 迁移管理」执行。
8. 在 `tests/` 对应子包补测试。

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

设计已为「错误码随业务模块走」预留，触发条件：某业务域长大、自成模块时。迁移步骤：

1. 在业务模块内建 `app/services/<domain>/errors.py`，定义该域的 `class <Domain>ErrorCode: ...`。
2. 把该域相关的内嵌命名空间类（连同其常量、对应的业务异常子类）整块从 core 搬过去。
3. 在 `app/core/exceptions/__init__.py` 把业务模块的错误码 re-export 回全局 `ErrorCode`。

**关键约束**：迁移后调用方写法 `ErrorCode.<Namespace>.<NAME>` **保持不变**，只有 import/定义位置变化——这是当前命名空间设计要守住的契约，新增错误码时不要破坏这种可迁移性（例如不要把多个业务域的码混塞进同一个命名空间类）。

## Alembic 迁移管理（核心：规避双轨爆炸）

### 铁律：`create_all` 与 `alembic` 不同库共存，绝不在同一库同时用

| 环境 | `DB_AUTO_CREATE` | 建表方式 | 跑 alembic？ |
|---|---|---|---|
| 开发 `.env.development` | `True` | `create_all`（启动自动） | **否**（表已建，跑 alembic 会报"表已存在"） |
| 测试 `.env.test` | `True` | `create_all` | **否** |
| 生产 `.env` | **`False`** | `alembic upgrade head` | **是** |

爆炸根因：开发库已经 `create_all` 建了表，又跑 `alembic upgrade` → baseline 试图重建已存在的表 → 报错。
**开发/测试环境根本不用 alembic**，直接靠 `create_all`；只有生产用 alembic，且生产绝不 `create_all`。

### 改模型后的正确流程（增量迁移，禁止重建全库）

1. 改 `app/models/<x>.py`，在 `app/models/__init__.py` 登记。
2. **不要**动 baseline 或已有迁移文件——它们是历史事实，不可改。
3. 生成增量迁移：
   ```bash
   # 生产环境配置下执行（确保能连到干净的库或 alembic 能对比差异）
   alembic revision --autogenerate -m "add <table>_<变更摘要>"
   ```
4. **检查生成的文件**：autogenerate 不完美，确认 `upgrade()` 只包含本次变更涉及的表，不要混入无关 op。
5. 提交前确认单一 head：
   ```bash
   alembic heads   # 必须只输出一行
   alembic history # 检查链路：base → baseline → ... → head
   ```
6. 生产部署：`alembic upgrade head`。

### 常见爆炸场景与规避

| 症状 | 原因 | 解法 |
|---|---|---|
| `alembic upgrade` 报"表已存在" | 开发库被 `create_all` 建过，又跑 alembic | 开发库不跑 alembic；或 `alembic stamp head` 标记当前状态为已应用 |
| autogenerate 生成空迁移 | 模型与 DB 已一致（`create_all` 已建） | 正常，删掉空迁移文件 |
| autogenerate 把已有表当成要新建 | baseline 与 `create_all` 的表定义有细微差异 | 以模型为准，手改迁移 op；不要用 autogenerate 的结果直接覆盖 baseline |
| 多 head（分支） | 两个迁移都指向同一个 down_revision | `alembic merge -m "merge heads" <head1> <head2>` 合并 |
| downgrade 后再 upgrade 报错 | 数据已存在，downgrade 删了表 | 开发环境直接 drop 整库重建，不要来回 downgrade |

### 开发环境快速重置（表结构大改时）

开发环境不要纠结 alembic 链，直接重建：
```bash
# 连 PG 删库重建（开发库 domefff）
psql -U postgres -c "DROP DATABASE IF EXISTS domefff;"
psql -U postgres -c "CREATE DATABASE domefff;"
# 重启服务，create_all 自动建所有表
python run.py --env 1
```

### 迁移文件命名约定

- 文件名：`<revision>_<动词>_<表名>.py`（如 `a1b2c3d4e5f6_add_refresh_tokens.py`）
- 一个迁移只做一件事（加表/加列/改列/加索引），不要把多个不相关变更塞进同一个迁移
- `down_revision` 必须指向当前 head，不要指向历史节点（会造成多 head）

## 不变量（贯穿全项目，勿打破）
- **DB 会话**：路由用 `Depends(get_db)`；路由外（worker/脚本/后台任务）用 `async with get_session() as db:`。两者都不自动提交，需显式 `await db.commit()`。
- **时间列**：模型时间列一律带时区——文件内用 `DateTime = _DateTime(timezone=True)` 别名模式（见现有 models）。
- **权限**：用依赖 `require_permission / require_role / require_superuser`（`app/middleware/rbac.py`），不要用装饰器。
- **中间件抛错**：中间件里要短路就 `return JSONResponse(...)`，**不要 `raise HTTPException`**（注册的处理器只覆盖路由层；中间件异常由最外层 `ExceptionHandlerMiddleware` 兜底映射状态码）。
- **中间件顺序**（`main.py`，后 `add` 的在外层）：CORS → 异常处理 → 安全头 → 日志 → 指标 → 限流 → 认证限流。
- **异常**：业务错误抛 `BaseAppException` 子类，别在路由里 `try/except` 吞掉再返回自定义格式；错误码一律用 `ErrorCode.*` 常量，禁止裸字符串（见「错误码（ErrorCode 注册表）」）。
- **日志**：`from app.core.loguru_logger import get_logger`；禁止 `print`、禁止直接配置 loguru handler。
- **Redis 可降级**：限流/缓存把 Redis 当增强项——未配置走内存、故障自动降级；不要把它写成强依赖。

## Git
需要 commit 时：`<type>(<scope>): <subject>`（type：feat/fix/refactor/chore/docs/test）。
