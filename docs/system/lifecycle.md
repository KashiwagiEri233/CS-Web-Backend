# 启动 / 关闭任务注册表（lifecycle registry）

## 概述

把应用启动 / 关闭的初始化逻辑从 `app/main.py` 解耦：各能力模块用 `@register_startup` /
`@register_shutdown` 装饰器**自注册**到全局注册表，`lifespan` 只调用 `run_startup()` /
`run_shutdown()` 遍历执行。新增启动任务无需回 `main.py` 改动——与项目「中心注册点」哲学
一致（同 API router、ORM 模型、中间件的登记方式）。

代码：`app/core/lifecycle/`（`registry.py` 注册表本体、`__init__.py` 触发各注册点 import）。

**职责边界**：
- 本模块负责：任务登记、按 priority 排序、critical 失败传播、统一日志。
- 本模块**不负责**：具体初始化逻辑（那些留在各自能力模块，如 DB 初始化在 `database.py`、
  RBAC seed 在 `services/rbac_init.py`）。

**运行时边界**：数据库 engine/session factory、Redis、OTel provider 和本注册表目前仍是
进程级资源，因此只支持“一进程一个活动应用”。`app/core/app_runtime.py` 会在 lifespan
进入时取得进程所有权；若同一进程并发启动第二个应用，会立即拒绝，避免两套生命周期
互相关闭资源。`create_app()` 创建的路由和中间件实例仍可独立用于不进入 lifespan 的测试。

## 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `register_startup` | `register_startup(name, priority=50, critical=True)` 装饰器 | 把协程函数登记为启动任务 |
| `register_shutdown` | `register_shutdown(name, priority=50)` 装饰器 | 把协程函数登记为关闭任务 |
| `run_startup` | `await run_startup() -> None` | 按 priority **升序**执行所有启动任务 |
| `run_shutdown` | `await run_shutdown() -> None` | 按 priority **降序**执行所有关闭任务 |

装饰器签名的协程约定：`async def task() -> None`（无参；所需依赖如 `db` 在函数体内
自行获取，如 `async with AsyncSessionLocal() as db:`）。

### 当前已注册任务

| 任务名 | 类型 | priority | critical | 位置 | 说明 |
|---|---|---|---|---|---|
| `database` | startup | 10 | **True** | `app/database.py` | 建库 + schema(Alembic upgrade/版本校验) + 连通性探测；失败拒绝启动 |
| `rbac_seed` | startup | 20 | True | `app/services/rbac_init.py` | 权限/角色/默认管理员；集群锁串行，失败拒绝启动 |
| `redis_probe` | startup | 30 | False* | `app/core/redis_client.py` | 探测 Redis；默认可降级。`REQUIRE_REDIS_FOR_SECURITY=True` 时失败 raise 拒绝启动 |
| `refresh_token_gc` | startup/shutdown | 40/30 | False | `app/services/token_gc.py` | 清理过期/撤销 refresh token；集群锁避免重复执行 |
| `exception_log_retention` | startup/shutdown | 45/25 | False | `app/services/exception_retention.py` | 按保留期清理异常日志；集群锁避免多 worker 重复执行 |
| `log_status` | startup | 90 | False | `app/main.py` | 输出访问地址 / 文档路径 |
| `telemetry` | shutdown | 10 | — | `app/core/observability.py` | flush 并释放 OTel providers |
| `redis` | shutdown | 20 | — | `app/core/redis_client.py` | 释放 Redis 连接 |

> 启动横幅 / AUTH_ENABLED 告警是应用级一次性展示（非幂等、无 priority 概念），**不进注册表**，
> 直接在 `lifespan` 内 `run_startup()` 之前输出。

## 配置

本模块无 `Settings` 字段。任务行为（是否执行某步、降级策略）由**各自能力模块**的配置控制
（如 `DB_AUTO_MIGRATE`、`REDIS_URL`、`OTEL_ENABLED`），注册表只管调度。

### priority 约定

| 段 | 含义 | 示例 |
|---|---|---|
| 10 | 基础设施（DB / schema） | `database` |
| 20 | 依赖基础设施的业务 seed | `rbac_seed` |
| 30 | 增强项探测 | `redis_probe` |
| 40–49 | 后台维护任务 | `refresh_token_gc`、`exception_log_retention` |
| 90 | 展示 / 收尾 | `log_status` |

新增任务按依赖关系选段：被依赖的 priority 小，依赖别人的 priority 大。同段内顺序不重要
（任务应彼此独立）。

## 依赖与协作

- 被 `app/main.py` 的 `lifespan` 调用（`run_startup` / `run_shutdown`）。
- 各注册点模块（database / rbac_init / redis_client / observability）反向 import
  `register_startup` / `register_shutdown` 装饰器。
- **触发登记**：`ensure_registrants_loaded()` 在 `run_startup` / `run_shutdown` 入口懒加载
  各注册点模块（core 基础设施 + service 业务任务列表分开放）。**core 不在 import 期
  反向 import service**，避免分层倒置。`main.py` 自身注册的任务在 `app.main` 被 import 时
  自登记，无需列入 registrant 列表。

## 降级与不变量

- **critical 任务失败 → 拒绝启动**（raise 中止，后续任务不执行）。数据库和 RBAC seed
  这类正确性基础设施标 critical。
- **非 critical 任务失败 → 仅告警继续**。Redis 探测、OTel 等增强项可降级；
  RBAC seed 属于鉴权基础设施，因此是 critical，失败会拒绝启动。
- **关闭阶段绝不抛错**：任何关闭任务异常都吞掉只记 warning，避免掩盖启动/业务异常或干扰退出码。
- **重名保护**：startup / shutdown 各自命名空间内重名注册立即抛 `ValueError`（防误用）。
- **执行顺序以 priority 为准**，不依赖 import 顺序（import 顺序只决定登记先后）。

## 测试

`tests/core/test_lifecycle.py`：覆盖 priority 升/降序、critical 传播、非 critical 降级、
关闭吞错、重名报错、装饰器返回原函数。通过 monkeypatch 临时接管全局注册表，隔离项目
模块已登记的真实任务（避免 run_startup 误触发建库等副作用）。

`tests/core/test_app_runtime.py`：覆盖活动应用互斥和非所有者不可释放进程资源。

## 扩展指引

### 加一个启动任务

1. 在任务所属模块（如 `app/services/foo_service.py`）写协程函数，加装饰器：
   ```python
   from app.core.lifecycle import register_startup

   @register_startup("foo_warmup", priority=25, critical=False)
   async def startup_foo_warmup() -> None:
       async with AsyncSessionLocal() as db:
           await FooService(db).warmup()
   ```
2. 若该模块**尚未**被 `lifecycle/__init__.py` 的 `_import_registrants()` 列出，追加一行 import。
3. core 失败会拒绝启动的才标 `critical=True`；其余一律 `critical=False`。
4. 选 priority：看依赖谁、被谁依赖（见上表约定）。
5. 需要清理资源的，配套加 `@register_shutdown`（关闭 priority 与启动对称：后启动的先关）。

### 常见坑

- **任务不执行**：99% 是忘记在 `_import_registrants()` 里 import 注册点模块，装饰器没被触发。
- **不要在 `run_startup` 内动态注册**：装饰器只在 import 期生效，运行期注册不会被执行。
- **不要把展示逻辑塞进注册表**：横幅、一次性提示这类非幂等输出留在 `lifespan` 里直接做。
