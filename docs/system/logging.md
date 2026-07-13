# 结构化日志

## 概述

`app/core/loguru_logger/` 统一封装 Loguru、标准库 logging 拦截、请求上下文和环境化
输出。业务代码只使用 `get_logger()`，不直接添加 handler。

## 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `init_logging` | `init_logging(settings)` | 幂等初始化日志 sink |
| `get_logger` | `get_logger(name=None) -> LoguruAdapter` | 获取带模块名的适配器 |
| `set_logging_context` | `set_logging_context(**fields)` | 绑定请求级字段 |
| `reset_logging_context` | `reset_logging_context(token)` | 恢复上下文 |
| `get_logging_context` | `get_logging_context() -> dict` | 读取当前上下文副本 |

## 配置

`LOG_PROFILE=dev|prod` 决定默认级别、JSON、控制台与文件输出；`LOG_LEVEL`、
`LOG_DIR`、`LOG_ROTATION`、`LOG_RETENTION` 等字段可覆盖 profile。

## 降级与不变量

- 日志上下文使用 `ContextVar`，请求结束必须 reset，避免跨请求污染。
- `request_id`、`user_id` 等结构化字段写入 Loguru `extra`，不能只拼到消息文本。
- 密码、token、数据库连接口令和客户端原始校验输入不得写入日志。
- 日志展示按 `TIMEZONE` 转换，存储和业务时间仍使用 UTC。

## 测试

`tests/core/test_structured_logging.py`、`test_exception_logging.py` 和
`test_exception_middleware.py` 覆盖结构化字段、异常及 request ID。

## 扩展指引

新增公共字段放入请求上下文；新增 sink 或格式只修改日志初始化模块，禁止在业务模块
直接配置 Loguru。

