# 异常处理

## 概述

项目用 `BaseAppException` 子类表达业务失败，由全局处理器转换为统一错误响应；未处理异常由最外层异常中间件兜底。
错误码集中在 `ErrorCode` 注册表，异常日志异步持久化，避免路由自行拼装错误 JSON。

代码：`app/core/exceptions/`、`app/models/exception_log.py`、`app/repositories/exception_log_repo.py`。

## 接口

### 公共类型与函数

| 符号 | 用途 |
|---|---|
| `BaseAppException` | 业务异常基类，承载状态码、错误码、消息和安全详情 |
| `ErrorCode` | 客户端错误码的单一事实源 |
| `setup_exception_handlers(app)` | 注册业务异常、FastAPI 校验、HTTP、数据库和兜底处理器 |
| `ExceptionHandlerMiddleware` | 捕获路由层外异常并按状态映射统一响应 |

### 管理接口

异常日志查询接口挂载于 `/api/v1/exceptions`，仅供超级用户使用；具体契约以
`app/api/v1/exceptions.py` 与 `app/schemas/exception_log.py` 为准。

## 响应与安全

统一错误响应包含 `success=false`、`error_code`、`message`、`status_code`、`timestamp`，按异常类型可带安全的 `details`。

- Pydantic 校验错误会移除原始 `input`，避免密码、令牌等请求值回显或落日志。
- 数据库异常只向客户端返回稳定错误码和通用消息，不返回驱动异常、SQL 或约束原文。
- 日志记录请求路径，不记录带查询参数的完整 URL。
- 业务异常必须引用 `ErrorCode.*`，禁止裸字符串错误码。
- 中间件需要短路时直接返回 `JSONResponse`，不要抛 `HTTPException`。

## 持久化与降级

异常日志通过独立数据库会话写入，失败只写应用日志，不覆盖原始 HTTP 响应。表结构由 Alembic 迁移维护；应用代码和测试不得调用 `create_all`。

## 扩展指引

1. 在 `base_exceptions.py` 定义或复用异常类。
2. 在 `error_codes.py` 对应命名空间登记错误码。
3. 从 `app/core/exceptions/__init__.py` 导出公共异常。
4. 只有需要专属转换逻辑时才在 `setup_exception_handlers` 注册处理器。
5. 补充 handler、middleware 和 service 层测试。

## 测试

主要覆盖位于 `tests/core/test_exception_handlers.py`、`tests/core/test_exception_handler_middleware.py`、
`tests/core/test_exception_logging.py` 和 `tests/services/test_exception_service.py`。
