# 测试

测试目录**镜像 `app/` 的结构**：被测模块在哪个包，测试就放在对应的 `tests/<同名包>` 下。

```
tests/
├── conftest.py          # 全局 fixture / 测试前置（先于任何 app.* 导入设置 SECRET_KEY 等）
├── core/                # 对应 app/core/
│   ├── test_cache.py            # app/core/cache（可降级通用缓存）
│   ├── test_rate_limit.py       # app/core/rate_limit（可降级限流）
│   └── test_exception_middleware.py  # app/core/exceptions（异常处理中间件状态码映射）
└── middleware/          # 对应 app/middleware/
    └── test_rbac_permissions.py # app/middleware/rbac（权限校验依赖）
```

## 约定

- 新增测试时，按被测模块所在的 `app/` 子包，放到 `tests/` 下的同名子包；缺哪个建哪个（记得加 `__init__.py`）。
- 文件名 `test_*.py`，函数 `test_*`，类 `Test*`（见 `pytest.ini`）。
- `asyncio_mode = auto`：异步测试直接写 `async def test_xxx()`，无需 `@pytest.mark.asyncio`。
- **单元测试不依赖外部服务**：用 monkeypatch / fake 隔离 Redis、数据库；需要会话时用 `app.database.get_session`。
- 需要真实数据库的集成测试，建议放在 `tests/integration/`（按需新建），并用独立测试库（见 `.env.test`）。

## 运行

```bash
python -m pytest                 # 全部
python -m pytest tests/core      # 仅某个子包
python -m pytest tests/core/test_cache.py -q
```
