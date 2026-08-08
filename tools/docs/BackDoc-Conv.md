# 后端编码规范（BackDoc-Conv）

> 更新人：3yearsZ
> 最后更新：2026-08-08（对齐代码约定 v0.9.8：补充 ASGI 中间件、LLM 双协议客户端与无 key 降级、Agent 工具循环、后台 asyncio 任务、camelCase 响应、迁移命名/head 等约定）
> 关联：通用工程规范见根 [`RootDoc-EngConv.md`](../../../docs/RootDoc-EngConv.md)；扩展约定见 `../AGENTS.md`；项目定位见 `../CLAUDE.md`；架构见 [BackDoc-01-Arch.md](BackDoc-01-Arch.md)

本项目的编码规范、目录组织与通用约定。**所有贡献者（含 AI Agent）在写代码前必须先读本文档**。

> 框架无关的通用工程规范（命名 / DRY / 圈复杂度 / 错误处理 / 安全 / 配置 / 测试 / Git）已提炼到根仓库 `../../../docs/RootDoc-EngConv.md`，本文档侧重 Python/FastAPI 强相关的分层、会话、迁移等约定。
> 项目级扩展约定（如何加模块、中心注册点、Alembic 迁移）见 `../AGENTS.md`；项目定位与硬性禁止项见 `../CLAUDE.md`。
> **约定类文档边界**：后端专项约定以本文档为权威；前端专项见 `CS-Web-Frontend/tools/docs/FrontDoc-01-Arch.md`；`docs/Onboarding.md` 附录 A 为新人聚合摘要（非权威），细则指回本文件与 RootDoc-EngConv。

> 文档优先级：场景内具体指令 > `../AGENTS.md` > `../CLAUDE.md` > 本文件 > 通用工作流。

> 术语统一：本文档中「**子仓库 / submodule**」专指 git 外部子仓库；app 内部的代码模块统称「**子模块**」。数据访问层仍称「**repositories/（数据访问层）**」，不混用「子仓库」一词，以免与 submodule 混淆。

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
alembic/           # Schema 迁移（开发/测试/生产唯一建表路径）
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
| 配置项 | `UPPER_SNAKE_CASE`（`.env` 与 `Settings` 字段同名） | `SECRET_KEY`, `DB_AUTO_MIGRATE` |

---

## 3. Python 与异步约定

- **全异步**：所有 IO（DB、Redis、HTTP）一律 `async def`；禁止在异步路径里调用阻塞 IO。
- **Python 版本**：跟随 `requirements.txt`，类型注解必填（公共函数签名、Pydantic 字段）。
- **DB 会话与事务边界**：
  - 路由内：`Depends(get_db)`。
  - 路由外（worker/脚本/后台任务）：`async with get_session() as db:`。
  - 会话**不自动提交**；出异常应回滚。
  - **Repository 只 flush，不 commit**（`BaseRepository` / 各 repo 写操作统一）。
  - **Service 负责 `await db.commit()`**（单步或跨多 repo 的业务事务）。
  - 禁止在路由层手写 commit（除非极少数运维脚本）。
- **时间列**：ORM 时间列一律带时区，使用 `DateTime = _DateTime(timezone=True)` 别名模式（参考现有 models）。
- **日志**：`from app.core.loguru_logger import get_logger`；**禁止 `print`、禁止直接配置 loguru handler**。

### 3.1 后台异步任务约定（asyncio 循环）

周期性 / 常驻后台任务（如 `app/services/token_gc.py` 的 refresh token 清理）遵循以下可复用模式：

- **注册方式**：用 `app/core/lifecycle`（包）的 `@register_startup` / `@register_shutdown` 装饰器自注册——装饰器定义在 `app/core/lifecycle/registry.py`，经 `app/core/lifecycle/__init__.py` 再导出，业务代码从 `app.core.lifecycle` 导入（如 `from app.core.lifecycle import register_startup, register_shutdown`）；`main.py` 的 `lifespan` 只调用 `run_startup()` / `run_shutdown()` 统一遍历执行，不手写启动序列。带 `priority`（启动顺序）与 `critical`（失败是否中止启动）参数。
- **循环体**：`asyncio.create_task(_gc_loop(interval))` 启动；循环内用 `asyncio.Event` 作停止信号，`await stop.wait()` 配合 `timeout=interval` 实现可打断的周期等待（勿用空转 `sleep`）。
- **单实例幂等**：需要「仅一个实例执行」的任务（如 GC、统计）用 Postgres 咨询锁 `pg_try_advisory_xact_lock` 抢占，未抢到则跳过本轮。
- **会话边界**：循环体内用 `async with get_session() as db:` 取会话，事务内 `await db.commit()`；禁止复用路由的 `Depends(get_db)`。
- **容错**：循环体单层 `try/except` 吞掉异常并 `logger.warning`，保证一轮失败不终止整个后台任务；`shutdown` 中 `stop.set()` 后 `await` 任务优雅退出（带超时，超时则 `cancel`）。

### 3.2 响应序列化约定（camelCase 传输）

API 的 JSON 入/出参统一 **camelCase 传输**，Python 属性名保持 snake_case：

- **出参 DTO**：继承 `app/schemas/base.py` 的 `TZModel`（内置 `alias_generator=to_camel` + `populate_by_name=True`，并统一把 `datetime` 转 `settings.TIMEZONE` 本地时区输出 ISO 字符串）。凡是经 `response_model` 返回的模型都应继承 `TZModel`（如 `AnnouncementOut`）。
- **入参 DTO**：请求体同样接受 camelCase（alias）与 snake_case（属性名）两种键名（`populate_by_name=True`），迁移期旧客户端用 snake_case 提交仍兼容。
- **错误响应**：统一 `ErrorResponse`（继承 `TZModel`），在 `ExceptionHandlerMiddleware` 中以 `model_dump(by_alias=True)` 输出 camelCase（`errorCode` / `statusCode` / `success` 等）。
- **裸 dict / SSE 响应**：未走 `response_model` 的路由（如 `auxilio.py` 的 `StreamingResponse`、字典返回）须**手动**使用 camelCase 键（如 `createdAt`、`toolCalls`），且 Python 内部变量保持 snake_case。

---

## 4. 代码质量红线

> 通用红线（文件大小 ~300 行、函数单一职责、DRY 三次法则、圈复杂度 ≤10、禁止散落魔法值）见根 [`RootDoc-EngConv.md`](../../../docs/RootDoc-EngConv.md) §二。本节只列后端专属补充。

### 4.1 后端专属补充

- **单一职责**：一个 service 只管一个业务域；禁止「订单+支付+物流」塞进一个 `order_service.py`。
- **提前返回降嵌套**：嵌套控制在 **3 层**以内，超过考虑重构控制流。
- **避免布尔参数控制多模式**：必要时改用枚举/策略对象/独立函数。

### 4.2 后端单一事实源

- **版本号**：唯一定义在 `app/__init__.py` 的 `__version__`；`FastAPI(version=)`、OTel `service.version`、启动日志等一律引用它，升级只改一处。
- **不硬编码 host:port**：绑定地址由 `run.py --host/--port`（uvicorn）决定，代码/日志**不要写死** 端口——`run.py` 默认 `--port 8000`，本地 `Makefile` 显式传 `--port 9000`；容器编排内 `docker-compose.yml` 用 `expose: 8000`。真实地址以 uvicorn 启动日志为准。
- **错误码**：用 `ErrorCode.*` 常量（见 `../AGENTS.md` 「错误码注册表」），禁止裸字符串。
- **边界**：`Settings` 里带注释的默认值本身就是单一来源，不算魔法值；本地化、仅 1–2 处的字面量按三次法则可不抽。

---

## 5. 错误处理约定

> 通用约定（禁止空 catch / 静默吞错、系统边界校验、不泄露敏感信息）见根 [`RootDoc-EngConv.md`](../../../docs/RootDoc-EngConv.md) §三。本节只列后端专属补充。

- **业务错误**：抛 `BaseAppException` 子类（`app/core/exceptions/base_exceptions.py`），由全局处理器统一映射状态码。
- **禁止**：在路由里 `try/except` 吞掉业务异常再返回自定义格式——绕过统一异常处理体系。
- **中间件短路**：中间件里要短路就 `return JSONResponse(...)`，**禁止 `raise HTTPException`**（异常处理器只覆盖路由层，中间件异常由最外层 `ExceptionHandlerMiddleware` 兜底）。

---

## 6. 安全约定

> 通用安全约定（禁止硬编码密钥/令牌/密码、参数化查询、日志禁止记录敏感信息）见根 [`RootDoc-EngConv.md`](../../../docs/RootDoc-EngConv.md) §四。本节只列后端专属补充。

- **密码**：使用 `app/core/security.py` 的哈希函数，禁止自实现加密。
- **权限**：用依赖 `require_permission / require_role / require_superuser`（`app/middleware/rbac.py`），**禁止用装饰器**。
- **SQL**：使用 SQLAlchemy 参数化查询，禁止字符串拼接 SQL 或命令。
- **输入校验**：Pydantic schema 在路由层校验；ORM 层信任 schema 已校验。

---

## 7. 配置约定

- 所有配置项定义在 `app/core/config.py` 的 `Settings` 类。
- **新增配置字段必须同步 `.env.example` 与 `.env.development`**，否则他人无法知道配置项。
- 环境分层（`run.py` **默认不带参数即加载 `.env.development`**；`--env 2`=测试、`--env 3`=生产）：
  - `.env.development`（开发，`DB_AUTO_MIGRATE=True`）—— **最全的参考样板**，所有可配字段都应在此列出。
  - `.env.test`（测试，同样走 Alembic）
  - `.env`（生产，`DB_AUTO_MIGRATE` 按部署策略）
- **`SECRET_KEY` 必须从环境变量设置，禁止占位值**。
- 新增「可选功能」的开关与参数（如 LLM 学习助手 `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_TIMEOUT` / `LLM_MAX_TOKENS` / `LLM_DAILY_BUDGET`）**必须集中在 `Settings`**，且默认值应使功能「默认关闭 / 安全降级」（如 `LLM_PROVIDER="none"` 即禁用，调用方捕获 `LLMConfigError` 降级为规则推荐）。切勿把可选功能的开关散落到模块级常量。
- 例外：队列开关 `QUEUE_ENABLED` 由可选队列模块自读环境/.env（不在 `Settings`），见 `BackDoc-Infra.md`。

---

## 8. 测试约定

- **目录结构**：`tools/tests/` 镜像 `app/` 子包结构；每个子包必须有 `__init__.py`（见 `../tools/tests/README.md`）。
- **命名**：测试文件 `test_*.py`，测试函数 `test_*`。
- **异步**：`pytest.ini` 段名必须是 `[pytest]`，`asyncio_mode=auto`，异步测试直接 `async def`，**不要** `@pytest.mark.asyncio`。
- **运行**：`python -m pytest`。
- **覆盖要求**：新增/修改业务逻辑必须补测试；至少覆盖正向、反向、边界三类路径。

---

## 9. Git 与提交

> 通用 Git 约定（提交格式 `<type>(<scope>): <subject>`、不主动 commit / push、侵入性操作先说明范围）见根 [`RootDoc-EngConv.md`](../../../docs/RootDoc-EngConv.md) §七。本节只列后端专属补充。

- **禁止提交**：`*.db`、`logs/`。本私有仓库允许跟踪环境配置文件；个人覆盖写入 `.env.local` / `.env.*.local`，不要提交。

---

## 10. 数据库迁移约定（摘要）

> 完整规则见 `../AGENTS.md` 的「Alembic 迁移管理」章节。

- **铁律**：全环境 **仅 Alembic**；禁止 `Base.metadata.create_all`。建库由 `DB_AUTO_CREATE_DATABASE` 控制，schema 仍只由 Alembic 管理。
- **启动**：`DB_AUTO_MIGRATE=True` 自动 `upgrade head`；`False` 仅校验版本不一致则 fail fast。
- **改模型流程**：改 model → 登记 `models/__init__.py` → `alembic revision --autogenerate -m "..."` → 检查 upgrade() → 确认单一 head → upgrade。
- **文件命名约定**：`alembic/versions/<revision_id>_<snake_case_描述>.py`（如 `d3e4f5a6b7c8_add_llm_usage_and_config.py`）。`revision_id` 由 autogenerate 生成（12 位十六进制）；`_描述` 用动词开头、下划线分隔，说明本次变更。禁止无描述或含空格的文件名。
- **当前单一 head**：`d3e4f5a6b7c8`（add_llm_usage_and_config）。每次合入前用 `alembic heads` 确认仍只有这一个 head；出现多 head 须先 `alembic merge` 再升级。
- **禁止**修改 baseline 或已有迁移文件（历史事实不可改）。
- **专属库**：本项目用 PG 库 `domefff`，**勿与其它项目共用一个库**。

---

## 11. 禁止事项汇总（来自 CLAUDE.md）

- 禁止前端渲染：Jinja2 / StaticFiles / HTMLResponse。
- 禁止 sqlite 作生产库（仅 PostgreSQL）。
- 禁止直接 `print` 或直接配置 loguru handler。
- 禁止提交 `*.db`、`logs/`；环境文件遵循本私有仓库的跟踪策略。
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
- [ ] 新增 ASGI 中间件是否纯 ASGI（非 BaseHTTPMiddleware）、埋点为 fire-and-forget 不阻塞主流程？
- [ ] 新增 LLM 调用点是否沿用双协议客户端 + 无 key 降级规则模式（捕获 `LLMConfigError`）？
- [ ] 出参 DTO 是否继承 `TZModel`（camelCase 传输）？裸 dict / SSE 是否手动 camelCase 键？
- [ ] 新增配置项（含可选功能开关）是否已同步 `.env.example` 与 `.env.development`？
- [ ] 新迁移文件是否遵循 `<revision_id>_<snake_case_描述>.py` 命名、合入前确认单一 head？

---

## 13. ASGI 中间件约定（横切关注点）

新增横切关注点（埋点、监控、限流、安全头等）默认以**纯 ASGI 中间件**实现，参考 `app/middleware/api_usage.py` 与 `app/middleware/monitoring.py`。

- **纯 ASGI，不用 BaseHTTPMiddleware**：直接实现 `async def __call__(self, scope, receive, send)`，避免 `BaseHTTPMiddleware` 在每个请求上的额外开销与缓冲。
- **注册**：在 `app/main.py` 的 `create_app()` 中用 `app.add_middleware(MiddlewareClass, ...)` 注册。Starlette 后注册的中间件处于更外层，故按「内 → 外」顺序添加（见 `main.py` 现有顺序：体积闸门最内、CORS 最外）。
- **fire-and-forget 埋点**：观测性写入（如 `api_usage` 落库）必须**不阻塞主响应**——在 `finally` 中用 `asyncio.create_task(self._log(...))` 异步写库，写入失败仅 `logger.debug` 吞掉，绝不抛出（观测性不能影响主流程）。
- **跳过自指噪声**：对 `/health`、`/readyz`、`/docs`、`/openapi.json` 及中间件自身统计接口设 `SILENT_PREFIXES`，`path.startswith(...)` 直接透传，避免统计自我引用与文档接口被埋点。
- **短路与异常**：中间件内要短路就 `return JSONResponse(...)`（或包一层 `send`），**禁止 `raise HTTPException`**——异常处理器只覆盖路由层，中间件异常由最外层 `ExceptionHandlerMiddleware` 兜底。
- **仅处理 http**：`__call__` 开头判断 `scope["type"] != "http"` 时直接 `await self.app(...)` 透传，避免影响 WebSocket / lifespan。

---

## 14. LLM 学习助手约定（Auxilio Agent）

LLM 相关代码集中在 `app/services/llm_client.py`（客户端）与 `app/services/auxilio_agent.py`（编排），配置在 `Settings` 的 `LLM_*` 字段。

### 14.1 客户端双协议 + 无 key 降级规则模式

`llm_client.stream_chat()` 是统一流式入口，对上层屏蔽底层协议差异：

- **双协议适配**：`provider=openai` → 走 OpenAI 兼容 `/chat/completions`（支持 DeepSeek / 通义 / Kimi / 本地 vLLM，经 `LLM_BASE_URL` 自定义网关）；`provider=anthropic` → 走 `https://api.anthropic.com/v1/messages`。两者都走 SSE 流式，并在内部做**消息格式互转**（`_to_anthropic_messages` 把 OpenAI 风格 `tool_calls` / `role=tool` 转 Anthropic 的 `tool_use` / `tool_result` blocks）。
- **统一事件流**：流式产出事件 dict——`delta`（增量文本）/ `tool_calls`（工具调用）/ `usage`（token 计量）/ `done` / `error`，上层（Agent / 路由）只消费这套事件，不感知协议。
- **配置优先级**：用户级配置 `overrides`（来自 `LlmConfig`，API Key 经 `totp_encryption` 解密）> 全局 `Settings`（`.env`）。`overrides` 缺省时回落全局。
- **无 key 降级规则模式**：`check_enabled(overrides)` 在 `LLM_PROVIDER="none"` 或无 `LLM_API_KEY` 时抛 `LLMConfigError`；调用方（`auxilio_agent.run_chat`）捕获后**降级为规则推荐摘要**（直接基于 `analyze_learning_profile` 等已有数据给出文字建议），而非报错。新增 LLM 调用点必须沿用此降级路径，禁止在 LLM 未配置时让接口 500。
- **流式错误**：上游 `httpx` 异常在客户端内转为 `{"type":"error",...}` 事件 yield，不向上抛，由编排层决定如何降级。

### 14.2 Agent 工具循环约定

`auxilio_agent.run_chat()` 编排「系统提示词注入 + Skills 工具调用 + 流式产出」：

- **固定轮数**：常量 `MAX_TOOL_ROUNDS = 3`（定义在 `auxilio_agent.py`），`for _round in range(MAX_TOOL_ROUNDS)` 控制工具循环上限，**禁止**改成无上限 `while True`，避免模型失控循环。
- **工具注册表**：可用工具在 `TOOL_SCHEMAS`（list[dict]，含 `name` / `description` / `parameters`）集中声明，并同时提供 OpenAI 与 Anthropic 两套 schema 转换（`_oai_tool_schema` / `_anthropic_tool_schema`）。新增工具须在此登记并补全两个协议的 schema。
- **执行与回填**：每轮消费 `tool_calls` → 逐个 `execute_tool(name, arguments, db, user)` 执行（异常转 `{"error":...}` 结果文本，不中断循环）→ 把 `assistant`（含 `tool_calls`）与 `tool` 消息回填 `messages`，进入下一轮。
- **事件透传**：向 SSE 透传 `delta` / `tool_call` / `tool_result` / `done` / `error` 事件；`done` 携带 `title`（会话标题候选）与 `usage`。
- **收尾**：若最后一轮只有工具调用无文本，补一句总结性 `delta`；最终 `yield {"type":"done","title":...}`。

### 14.3 用量计量与成本护栏

- **用量落库**：每次模型调用在路由层（如 `auxilio.py` 的 `event_stream` 的 `finally`）写 `LlmUsageLog`（provider / model / prompt_tokens / completion_tokens / total_tokens / latency_ms），供工作台统计与 `get_llm_usage_stats` 工具查询。
- **预算配置**：`LLM_DAILY_BUDGET` 为单用户单日调用预算（0 = 不限制），意图防止成本失控（落实状态见第 15 章信息缺口声明）。

---

## 15. 信息缺口声明

以下为本次对齐代码时发现、但代码 / 配置尚未完全落实或存在偏差的项，需后续补齐或由负责人确认；未落实项以 `[待填写]` 标注。

1. ~~**`LLM_DAILY_BUDGET` 未强制**~~ → **已落实（2026-08-08）**：在 `auxilio_agent.run_chat` 调用模型前按用户维度累加当日 `llm_usage_logs.total_tokens`，达 `LLM_DAILY_BUDGET`（单位：千 tokens/日，默认 200 = 20 万 tokens；0 = 不限制）即停止调用并提示。配置注释已同步（`config.py`）。
2. ~~**`LLM_*` 未同步环境样板**~~ → **已补齐（2026-08-08）**：`.env.example`、`.env.docker.example`、`.env.development` 均已增加 `LLM_*` 可选段（含默认值与 `LLM_PROVIDER=none` 降级说明）。
3. ~~**`auxilio_agent` 直连 DB 与分层规则偏差**~~ → **已收敛（2026-08-08）**：`execute_tool` 的查询全部迁移至新仓储 `app/repositories/auxilio_tool_repo.py`（`AuxilioToolRepository`，只读），service 层不再直发 SQL，符合第 1 章分层铁律；SQL 语义与重构前一致。
4. **术语确认**：本文「子仓库 / submodule」仅指 git 外部子仓库，「子模块」指 app 内代码模块；数据访问层沿用「repositories/（数据访问层）」称谓，未改称「子仓库」。若团队另有约定请指正。
