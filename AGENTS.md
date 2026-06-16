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

## 中心注册点（加东西必须在这里登记，否则不生效或散落）

| 新增 | 放哪 | 必须登记到 |
|---|---|---|
| API 资源 | `app/api/v1/<name>.py`（`router = APIRouter()`） | `app/api/v1/__init__.py` → `api_router.include_router(router, prefix=..., tags=[...])` |
| ORM 模型 | `app/models/<name>.py` | `app/models/__init__.py`：import + 加入 `__all__`（否则 `create_all` 与 alembic autogenerate 都看不到） |
| 业务异常 | 继承 `BaseAppException`（`app/core/exceptions/base_exceptions.py`） | `app/core/exceptions/__init__.py` 的 `__all__`；若需专属处理逻辑，再在 `setup_exception_handlers` 注册 |
| 中间件 | `app/middleware/<name>.py` | `app/main.py` 按顺序 `add_middleware`（见下方顺序约定） |
| 配置项 | `app/core/config.py` 的 `Settings` | 同步加到 `.env.example` |
| 迁移 | `alembic revision --autogenerate -m "..."`（改完模型后） | 提交前确认只有单一 head |
| 测试 | `tests/<镜像 app 的子包>/test_*.py` | 子包需有 `__init__.py`（见 `tests/README.md`） |

## 加一个 API 资源（标准配方）
1. **模型** `app/models/<x>.py` → 在 `app/models/__init__.py` import 并加进 `__all__`。
2. **schema** `app/schemas/<x>.py`：Pydantic v2（`model_config = ConfigDict(...)`，需从 ORM 转换时加 `from_attributes=True`）。
3. **repository** `app/repositories/<x>_repo.py`：构造函数收 `db: AsyncSession`，只做数据访问。
4. **service** `app/services/<x>_service.py`：构造函数收 `db`，写业务逻辑；不依赖 `Request`（这样 worker/脚本也能复用）。
5. **路由** `app/api/v1/<x>.py`：端点用 `Depends(get_db)`，鉴权用 `Depends(require_permission("<res>","<act>"))`。
6. 在 `app/api/v1/__init__.py` 注册 router。
7. `alembic revision --autogenerate` 生成迁移。
8. 在 `tests/` 对应子包补测试。

## 不变量（贯穿全项目，勿打破）
- **DB 会话**：路由用 `Depends(get_db)`；路由外（worker/脚本/后台任务）用 `async with get_session() as db:`。两者都不自动提交，需显式 `await db.commit()`。
- **时间列**：模型时间列一律带时区——文件内用 `DateTime = _DateTime(timezone=True)` 别名模式（见现有 models）。
- **权限**：用依赖 `require_permission / require_role / require_superuser`（`app/middleware/rbac.py`），不要用装饰器。
- **中间件抛错**：中间件里要短路就 `return JSONResponse(...)`，**不要 `raise HTTPException`**（注册的处理器只覆盖路由层；中间件异常由最外层 `ExceptionHandlerMiddleware` 兜底映射状态码）。
- **中间件顺序**（`main.py`，后 `add` 的在外层）：CORS → 异常处理 → 安全头 → 日志 → 指标 → 限流 → 认证限流。
- **异常**：业务错误抛 `BaseAppException` 子类，别在路由里 `try/except` 吞掉再返回自定义格式。
- **日志**：`from app.core.loguru_logger import get_logger`；禁止 `print`、禁止直接配置 loguru handler。
- **Redis 可降级**：限流/缓存把 Redis 当增强项——未配置走内存、故障自动降级；不要把它写成强依赖。

## Git
需要 commit 时：`<type>(<scope>): <subject>`（type：feat/fix/refactor/chore/docs/test）。
