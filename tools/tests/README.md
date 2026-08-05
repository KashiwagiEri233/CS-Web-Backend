# 测试

测试目录**镜像 `app/` 的结构**：被测模块在哪个包，测试就放在对应的 `tools/tests/<同名包>` 下。

```
tools/tests/
├── conftest.py          # 全局 fixture / 测试前置（先于任何 app.* 导入设置 SECRET_KEY 等）
├── core/                # 对应 app/core/
│   ├── test_cache.py            # app/core/cache（可降级通用缓存）
│   ├── test_rate_limit.py       # app/core/rate_limit（可降级限流）
│   └── test_exception_middleware.py  # app/core/exceptions（异常处理中间件状态码映射）
└── middleware/          # 对应 app/middleware/
    └── test_rbac_permissions.py # app/middleware/rbac（权限校验依赖）
```

## 约定

- 新增测试时，按被测模块所在的 `app/` 子包，放到 `tools/tests/` 下的同名子包；缺哪个建哪个（记得加 `__init__.py`）。
- 文件名 `test_*.py`，函数 `test_*`，类 `Test*`（见 `pytest.ini`）。
- `asyncio_mode = auto`：异步测试直接写 `async def test_xxx()`，无需 `@pytest.mark.asyncio`。
- **单元测试不依赖外部服务**：用 monkeypatch / fake 隔离 Redis、数据库；需要会话时用 `app.database.get_session`。
- 需要真实数据库的集成测试，建议放在 `tools/tests/integration/`（按需新建），并用独立测试库（见 `.env.test`）。

## 数据库隔离

Pytest 在导入应用前强制加载 `.env.test`，并拒绝连接数据库名不含 `test` 的地址。
CI 可通过 `TEST_DATABASE_URL` 覆盖测试库；设置 `REQUIRE_INTEGRATION_DB=1` 后，
数据库不可用会让测试失败，不再静默跳过。测试模式使用 SQLAlchemy `NullPool`，
避免 pytest 的多个事件循环复用 asyncpg 连接。

Redis/arq 集成同理使用 `TEST_REDIS_URL`；CI 设置 `REQUIRE_INTEGRATION_REDIS=1`，
因此缓存、限流、黑名单、故障恢复以及 worker 重试链路缺少真实 Redis 时会失败。

默认测试命令同时统计分支覆盖率并要求总覆盖率不低于 70%；报告写入
`build/coverage.xml`。

## 运行

```bash
python -m pytest                 # 全部
python -m pytest tools/tests/core      # 仅某个子包
python -m pytest tools/tests/core/test_cache.py -q
```
