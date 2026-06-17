# FastAPI 异常处理系统

本文档介绍了为 FastAPI 应用程序设计和实现的完整异常处理系统。

## 概述

异常处理系统提供以下功能：

- 自定义异常类体系
- 全局异常处理器
- 统一的错误响应格式
- 结构化异常日志记录
- 异常统计和分析
- 异常模式检测
- 异常告警机制

## 核心组件

### 1. 自定义异常类

#### 基础异常类

- `BaseAppException`: 所有自定义异常的基础类
- `BusinessException`: 业务逻辑异常 (400)
- `AuthenticationException`: 认证异常 (401)
- `AuthorizationException`: 授权异常 (403)
- `ValidationException`: 验证异常 (422)
- `NotFoundException`: 资源未找到异常 (404)
- `ConflictException`: 冲突异常 (409)
- `DatabaseException`: 数据库异常 (500)
- `ExternalServiceException`: 外部服务异常 (502)
- `RateLimitException`: 限流异常 (429)

#### 业务特定异常

- `UserAlreadyExistsException`: 用户已存在异常
- `InvalidCredentialsException`: 无效凭据异常
- `UserNotActiveException`: 用户未激活异常
- `PermissionDeniedException`: 权限拒绝异常
- `ResourceNotFoundException`: 资源未找到异常

### 2. 全局异常处理器

全局异常处理器捕获所有异常并返回统一的错误响应格式：

```python
# 在 main.py 中设置全局异常处理器
from app.core.exceptions import setup_exception_handlers

app = FastAPI()
setup_exception_handlers(app)
```

### 3. 统一错误响应格式

所有错误响应都遵循统一的格式：

```json
{
  "success": false,
  "error_code": "ERROR_CODE",
  "message": "错误描述",
  "status_code": 400,
  "details": {},
  "context": {
    "request_id": "req_123",
    "user_id": "user_456",
    "endpoint": "POST /api/v1/users",
    "timestamp": "2023-01-01T12:00:00.000Z"
  },
  "traceback_id": "trace_abc123"
}
```

### 4. 异常日志记录系统

异常日志记录系统提供以下功能：

- 结构化日志记录
- 异常统计分析
- 异常模式检测
- 异常告警
- 指标收集

### 5. 数据库模型

异常日志相关的数据库表：

- `exception_logs`: 异常日志记录
- `exception_patterns`: 异常模式
- `exception_alerts`: 异常告警
- `exception_metrics`: 异常指标

## 使用指南

### 1. 抛出自定义异常

```python
from app.core.exceptions import (
    UserAlreadyExistsException,
    InvalidCredentialsException,
    NotFoundException
)

# 用户已存在
raise UserAlreadyExistsException(username="john_doe")

# 无效凭据
raise InvalidCredentialsException()

# 资源未找到
raise NotFoundException(
    resource_type="用户",
    resource_id=123
)
```

### 2. 记录异常

```python
from app.services.exception_service import ExceptionService
from app.database import get_db

async def some_function():
    db = await get_db()
    exception_service = ExceptionService(db)
    
    try:
        # 业务逻辑
        pass
    except Exception as e:
        # 记录异常
        await exception_service.record_exception(
            exception=e,
            request_context={
                "request_id": "req_123",
                "user_id": "user_456",
                "endpoint": "/api/v1/some-endpoint",
                "method": "POST"
            }
        )
```

### 3. 查询异常日志

```python
# API 端点
GET /api/v1/exceptions/logs?skip=0&limit=100&exception_type=ValueError

# 服务方法
from app.services.exception_service import ExceptionService

exception_service = ExceptionService(db)
logs, total = await exception_service.get_exception_logs(
    skip=0,
    limit=100,
    exception_type="ValueError"
)
```

### 4. 异常统计

```python
# API 端点
GET /api/v1/exceptions/statistics?time_window_hours=24

# 服务方法
stats = await exception_service.get_exception_statistics(24)
```

### 5. 异常模式分析

```python
# API 端点
GET /api/v1/exceptions/patterns?time_window_hours=24

# 服务方法
patterns = await exception_service.analyze_exception_patterns(24)
```

### 6. 异常告警

```python
# API 端点
GET /api/v1/exceptions/alerts

# 确认告警
PUT /api/v1/exceptions/alerts/{alert_id}/acknowledge

# 解决告警
PUT /api/v1/exceptions/alerts/{alert_id}/resolve
```

## 最佳实践

### 1. 异常选择

- 使用 `AuthenticationException` 处理认证失败
- 使用 `AuthorizationException` 处理权限不足
- 使用 `ValidationException` 处理数据验证失败
- 使用 `NotFoundException` 处理资源未找到
- 使用 `ConflictException` 处理资源冲突
- 使用 `DatabaseException` 处理数据库错误
- 使用 `BusinessException` 处理其他业务逻辑错误

### 2. 异常消息

- 提供清晰、具体的错误消息
- 避免暴露敏感信息
- 支持国际化（如果需要）
- 包含足够的上下文信息

### 3. 异常日志

- 记录足够的上下文信息
- 包含请求ID和用户ID
- 记录异常堆栈
- 定期分析和清理日志

### 4. 异常监控

- 设置异常阈值
- 配置异常告警
- 定期检查异常模式
- 及时处理高优先级异常

## 迁移指南

如果您想将现有的异常处理迁移到新的系统，请按照以下步骤：

1. 替换 `HTTPException` 为相应的自定义异常
2. 更新中间件以使用新的异常类型
3. 更新 API 端点以使用新的异常类型
4. 配置全局异常处理器
5. 运行测试以确保一切正常工作

## 测试

运行异常处理系统的测试：

```bash
pytest tests/test_exceptions.py -v
```

## 扩展

如果需要扩展异常处理系统，可以：

1. 添加新的自定义异常类
2. 更新全局异常处理器
3. 扩展异常日志记录系统
4. 添加新的异常检测模式
5. 配置更多的告警渠道

## 故障排除

### 常见问题

1. **异常未被捕获**
   - 确保已设置全局异常处理器
   - 检查异常处理器顺序

2. **异常响应格式不一致**
   - 确保使用自定义异常类
   - 检查异常处理器是否正确设置

3. **异常日志未记录**
   - 检查数据库连接
   - 确保异常服务正确初始化

### 调试技巧

1. 检查异常日志
2. 使用 traceback_id 跟踪异常
3. 查看异常模式
4. 检查异常统计