# AGENTS.md

本文件为 AI Agent（Codex / Claude Code / 其他自动化工具）提供项目工作流指令。作用域内优先级高于 Agent 的通用行为约定。

---

## 1. 能力发现优先

开始任何任务前，必须先：
1. 检查可用的 Skills 和 MCP 工具。
2. 读取本文件和 `CLAUDE.md`。
3. 确认当前工作目录和文件结构。

## 2. 任务路由

| 意图 | 路由 |
|---|---|
| 已有代码功能实现/修改 | `code-change-workflow` |
| 线上故障/行为异常定位 | `root-cause-debugging` |
| 代码审查/质量评估 | `TRAE-code-review` |
| 文档/表格/PPT/PDF | 对应文件类型 Skill |

## 3. 代码修改工作流

### 3.1 动手前
- 读取目标文件及上下游依赖（调用方、被调用方、类型定义）。
- 确认是否存在可复用的现有实现，优先复用。
- 确认需求假设与代码事实是否一致。

### 3.2 实现约束
- **最小改动半径**：只改实现需求所必需的内容。
- **保持分层**：api → service → repository → model，禁止跨层。
- **保持兼容**：修改公共函数签名时，新增参数提供默认值。
- **风格一致**：新代码必须像项目原有代码（异步、命名、错误处理方式）。

### 3.3 完成后
- 扫描同类实现和全部调用点，确认无遗漏。
- 运行 `python -m py_compile` 覆盖改动文件。
- 如涉及业务逻辑变更，补充或更新 `tests/` 下的测试。

## 4. 项目特定约束

### 4.1 纯后端
- 本项目是纯后端 REST API 脚手架。
- 禁止引入 Jinja2、StaticFiles、HTMLResponse 或任何前端渲染逻辑。
- 所有接口返回 JSON。

### 4.2 数据库
- 生产数据库为 PostgreSQL（asyncpg）。
- ORM 层使用 SQLAlchemy 2.0 async 风格。
- 迁移使用 Alembic，`alembic/env.py` 已配置 asyncpg → psycopg2 的 URL 转换。

### 4.3 日志
- 日志器统一通过 `from app.core.loguru_logger import get_logger` 获取。
- 日志配置在 `main.py` lifespan 中调用 `configure_logging`，根据 `settings.DEBUG` 自动切换开发级/线上级。
- 禁止在代码中直接配置 loguru handler（避免全局副作用）。

### 4.4 异常
- 业务异常继承 `app.core.exceptions.base_exceptions.BaseAppException`。
- 全局异常处理器在 `main.py` 中通过 `setup_exception_handlers(app)` 注册。
- 禁止在路由层用 `try/except` 吞掉异常后返回自定义错误格式，应抛出 `BaseAppException` 子类。

### 4.5 配置
- 所有环境变量通过 `app/core/config.py` 的 `Settings` 类管理。
- `.env.example` 必须与 `Settings` 字段一一对应，新增字段时同步更新。
- `SECRET_KEY` 必须设置，禁止使用占位值。

## 5. 测试约定

- 测试文件放在 `tests/` 目录。
- 使用 pytest + pytest-asyncio。
- 异步测试用 `@pytest.mark.asyncio`。
- 测试数据库使用独立的测试配置（`.env.test`）。

## 6. Git 规范

- 不主动 commit，除非用户明确要求。
- 不主动 push。
- commit message 用中文，格式：`<type>(<scope>): <subject>`。
  - type: feat / fix / refactor / chore / docs / test
  - 示例：`feat(logging): 支持开发级/线上级日志配置切换`

## 7. 输出规范

- 侵入性改造（删除文件、改变公共接口、改变数据库结构）必须先说明范围，获得确认后再执行。
- 交付时说明：改了什么、验证了什么、生效前提、未覆盖的边界。
- 禁止伪造工具输出、测试结果或完成状态。
