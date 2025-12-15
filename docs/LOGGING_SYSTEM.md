# 高级日志系统文档

## 概述

本文档描述了FastAPI项目中实现的高级日志系统，该系统与Python标准库logging兼容，同时提供了结构化日志记录、多目标输出、上下文追踪和性能监控等高级功能。

## 功能特性

### 核心功能
- **标准logging兼容**: 完全兼容Python标准库logging接口
- **结构化日志**: 基于structlog的结构化日志记录
- **多目标输出**: 支持控制台、文件、数据库等多种输出目标
- **日志级别控制**: 可配置的日志级别和过滤
- **异步处理**: 支持异步日志写入，提高性能

### 高级功能
- **请求上下文追踪**: 自动追踪请求生命周期
- **分布式追踪**: 支持Trace ID和Span ID
- **性能监控**: 自动记录操作性能
- **慢查询检测**: 检测和记录慢数据库查询
- **系统资源监控**: 监控CPU、内存、磁盘等系统资源
- **自定义告警**: 可配置的性能告警机制

## 架构设计

### 系统架构

```
应用层 (FastAPI/业务代码)
    ↓
适配器层 (LoggingAdapter)
    ↓
结构化日志层 (Structlog)
    ↓
处理器层 (Processors)
    ↓
输出层 (Handlers)
    ↓
控制台/文件/数据库
```

### 目录结构

```
app/core/logging/
├── __init__.py                    # 主要入口和便捷函数
├── logging_adapter.py            # 标准logging兼容适配器
├── structured_logger.py          # 结构化日志核心
├── context.py                    # 上下文追踪和管理
├── performance.py                # 性能监控和慢查询检测
├── database_integration.py       # 数据库日志存储集成
└── handlers/                     # 输出处理器
    ├── __init__.py
    ├── base.py                   # 处理器基类
    ├── console.py                # 控制台输出处理器
    ├── file.py                   # 文件输出处理器
    └── database.py               # 数据库输出处理器
```

## 快速开始

### 基础配置

```python
from app.core.logging import configure_logging, get_logger

# 配置日志系统
configure_logging(
    level="INFO",
    enable_console=True,
    enable_file=True,
    log_dir="logs",
    app_name="my_app"
)

# 获取日志记录器
logger = get_logger("my_module")

# 记录日志
logger.info("应用启动", version="1.0.0")
logger.warning("配置项缺失", config_key="database_url")
logger.error("连接失败", service="database", error="Connection timeout")
```

### 上下文追踪

```python
from app.core.logging import set_logging_context, LoggingContextManager

# 设置全局上下文
set_logging_context(request_id="req-123", user_id=456)

# 使用上下文管理器
with LoggingContextManager(operation="data_processing", step="validation"):
    logger.info("验证数据格式", record_count=100)
    
    with LoggingContextManager(substep="cleaning"):
        logger.info("清理数据", cleaned_count=95)
    
    logger.info("数据处理完成")
```

### 性能监控

```python
from app.core.logging import performance_tracked, monitor_performance

# 使用装饰器监控函数性能
@performance_tracked("user_query")
def fetch_users():
    # 模拟慢操作
    time.sleep(0.5)
    return [{"id": 1, "name": "Alice"}]

# 使用上下文管理器监控代码块性能
with monitor_performance("database_query", query_type="SELECT", table="users"):
    # 执行数据库查询
    users = fetch_users()
    logger.info("查询完成", result_count=len(users))
```

### FastAPI集成

```python
from fastapi import FastAPI
from app.core.logging import integrate_with_fastapi

# 创建FastAPI应用
app = FastAPI(title="我的应用")

# 集成日志系统
app = integrate_with_fastapi(
    app,
    level="INFO",
    enable_console=True,
    enable_file=True,
    enable_performance=True,
    log_dir="logs"
)

# 路由处理
@app.get("/api/users")
async def get_users():
    logger = get_logger("api.users")
    logger.info("获取用户列表")
    return [{"id": 1, "name": "Alice"}]
```

## 高级配置

### 完整配置示例

```python
from app.core.logging import AdvancedLoggingSystem, DatabaseConfig

# 创建日志系统实例
logging_system = AdvancedLoggingSystem()

# 配置系统
logging_system.configure(
    level="INFO",
    
    # 控制台配置
    enable_console=True,
    console_format="colored",
    
    # 文件配置
    enable_file=True,
    log_dir="logs",
    app_name="my_app",
    file_max_size_mb=10,
    file_backup_count=5,
    
    # 数据库配置
    enable_database=True,
    database_config=DatabaseConfig(
        host="localhost",
        port=5432,
        database="app_logs",
        username="postgres",
        password="password"
    ),
    database_table="application_logs",
    
    # 性能监控配置
    enable_performance=True,
    performance_thresholds={
        "api_request": {"warning": 500.0, "error": 1000.0, "sample_rate": 1.0},
        "database_query": {"warning": 200.0, "error": 500.0, "sample_rate": 0.5},
        "user_authentication": {"warning": 300.0, "error": 800.0, "sample_rate": 1.0}
    },
    slow_query_threshold_ms=1000.0,
    monitor_resources=True,
    resource_interval=60.0
)
```

### 性能阈值配置

```python
from app.core.logging import performance_monitor

# 设置性能阈值
performance_monitor.set_threshold(
    "user_api_call",
    warning_threshold_ms=500.0,   # 500ms触发警告
    error_threshold_ms=1000.0,    # 1000ms触发错误
    sample_rate=1.0,              # 100%采样率
    enabled=True
)

# 设置采样率（只监控部分请求）
performance_monitor.set_threshold(
    "health_check",
    warning_threshold_ms=100.0,
    error_threshold_ms=200.0,
    sample_rate=0.1,              # 10%采样率
    enabled=True
)
```

### 自定义告警处理

```python
# 自定义告警处理器
def custom_alert_handler(alert):
    """处理性能告警"""
    if alert.threshold_type == "error":
        # 发送紧急通知
        send_notification(
            f"性能告警: {alert.operation_name} 耗时 {alert.duration_ms:.2f}ms",
            severity="high"
        )
    elif alert.threshold_type == "warning":
        # 记录到监控系统
        monitoring_system.record_metric(
            "slow_operation",
            alert.duration_ms,
            tags={"operation": alert.operation_name}
        )

# 注册告警处理器
performance_monitor.add_alert_handler(custom_alert_handler)
```

## 数据库集成

### 配置数据库日志

```python
from app.core.logging import setup_database_logging, DatabaseConfig

# 配置数据库日志存储
await setup_database_logging(
    host="localhost",
    port=5432,
    database="app_logs",
    username="postgres",
    password="password",
    table_name="application_logs",
    enabled=True,
    batch_size=100,
    flush_interval=5.0
)
```

### 查询日志数据

```python
from app.core.logging import get_database_logger
from datetime import datetime

# 获取数据库日志记录器
db_logger = get_database_logger()

# 查询日志
logs = await db_logger.query_logs(
    start_time=datetime(2023, 1, 1),
    end_time=datetime(2023, 1, 31),
    level="ERROR",
    limit=100
)

# 获取统计信息
stats = await db_logger.get_log_statistics(
    start_time=datetime(2023, 1, 1),
    end_time=datetime(2023, 1, 31)
)

# 清理旧日志
deleted_count = await db_logger.cleanup_old_logs(days_to_keep=30)
```

## 性能监控详解

### 操作性能监控

```python
# 装饰器方式
@performance_tracked("user_registration")
def register_user(user_data):
    # 用户注册逻辑
    pass

# 上下文管理器方式
with monitor_performance("password_hashing", algorithm="bcrypt"):
    hashed_password = hash_password(password)
```

### 数据库查询监控

```python
# 装饰器方式
@slow_query_tracked("user_search", database="app_db", table="users")
def search_users(query):
    # 搜索用户
    pass

# 上下文管理器方式
with monitor_database_query(
    "SELECT * FROM products WHERE price > ?",
    database="shop_db",
    table="products",
    min_price=100
):
    products = execute_query(query, [100])
```

### 获取性能数据

```python
# 获取性能指标
metrics = performance_monitor.get_metrics(
    operation_name="user_api_call",
    start_time=time.time() - 3600,  # 最近1小时
    limit=100
)

# 获取告警
alerts = performance_monitor.get_alerts(
    threshold_type="error",
    limit=50
)

# 获取统计信息
stats = performance_monitor.get_statistics()
for operation, stat in stats.items():
    print(f"{operation}: 平均耗时 {stat['avg_duration']:.2f}ms, "
          f"错误率 {stat['error_rate']*100:.1f}%")
```

## 迁移指南

### 从现有日志系统迁移

如果您已经在项目中使用了日志系统，可以按照以下步骤迁移：

1. **保留现有代码兼容性**
   ```python
   # 现有代码
   from app.core.logging import log_user_action, log_security_event
   
   # 这些函数仍然可用，现在会自动使用新系统
   log_user_action(123, "login", "auth", {"ip": "192.168.1.1"})
   log_security_event("failed_login", 123, {"reason": "invalid_password"})
   ```

2. **逐步增强现有日志**
   ```python
   # 添加上下文信息
   logger = get_logger("auth")
   
   # 现有方式
   logger.info("User logged in", user_id=123)
   
   # 增强方式
   with LoggingContextManager(operation="login", service="auth"):
       logger.info("User logged in", user_id=123, method="password")
   ```

3. **添加性能监控**
   ```python
   # 现有函数
   def authenticate_user(username, password):
       # 认证逻辑
       pass
   
   # 添加性能监控
   @performance_tracked("user_authentication")
   def authenticate_user(username, password):
       # 认证逻辑
       pass
   ```

## 最佳实践

### 日志级别使用

- **DEBUG**: 详细的调试信息，仅在开发环境使用
- **INFO**: 一般信息，记录重要的业务流程
- **WARNING**: 警告信息，可能的问题但不影响功能
- **ERROR**: 错误信息，功能异常但可以继续
- **CRITICAL**: 严重错误，导致系统不可用

### 日志内容规范

```python
# 好的日志示例
logger.info(
    "用户登录成功",
    user_id=123,
    login_method="password",
    ip_address="192.168.1.1",
    session_id="sess-abc123"
)

# 避免的日志示例
logger.info("登录成功")  # 缺少关键信息
logger.info(f"用户 {user_id} 登录成功")  # 不结构化
```

### 上下文使用

```python
# 推荐：设置请求级别的上下文
set_logging_context(
    request_id=request_id,
    user_id=user_id,
    operation=operation_name
)

# 推荐：使用上下文管理器跟踪操作
with LoggingContextManager(step="validation"):
    # 验证逻辑
    
with LoggingContextManager(step="processing"):
    # 处理逻辑
```

### 性能监控

```python
# 推荐：为关键操作设置性能监控
@performance_tracked("database_query", table="users")
def get_users():
    pass

# 推荐：为慢操作设置慢查询监控
@slow_query_tracked("report_generation", database="analytics")
def generate_report():
    pass
```

## 故障排除

### 常见问题

1. **日志文件未生成**
   - 检查日志目录是否存在且有写权限
   - 确认文件处理器已正确配置

2. **上下文信息丢失**
   - 确保在使用日志前设置了上下文
   - 检查是否有上下文重置操作

3. **性能监控未工作**
   - 确认性能监控已启用
   - 检查阈值设置是否合理

4. **数据库日志存储失败**
   - 检查数据库连接配置
   - 确认数据库表已创建

### 调试技巧

```python
# 启用调试模式
configure_logging(level="DEBUG", enable_console=True)

# 检查当前上下文
from app.core.logging import get_logging_context
context = get_logging_context()
print(f"当前上下文: {context}")

# 检查性能监控状态
from app.core.logging import performance_monitor
stats = performance_monitor.get_statistics()
print(f"性能统计: {stats}")
```

## API参考

### 核心函数

#### configure_logging()
配置日志系统的主函数。

**参数:**
- level (str|int): 日志级别，默认为INFO
- enable_console (bool): 是否启用控制台输出
- enable_file (bool): 是否启用文件输出
- enable_database (bool): 是否启用数据库输出
- enable_performance (bool): 是否启用性能监控
- log_dir (str): 日志文件目录
- app_name (str): 应用名称
- database_config (DatabaseConfig): 数据库配置
- performance_thresholds (dict): 性能阈值配置

#### get_logger(name=None)
获取日志记录器实例。

**参数:**
- name (str): 日志记录器名称，可选

**返回:**
- LoggingAdapter: 日志记录器实例

### 上下文管理

#### set_logging_context(**kwargs)
设置全局日志上下文。

**参数:**
- **kwargs: 上下文键值对

#### LoggingContextManager(**kwargs)
上下文管理器类。

**参数:**
- **kwargs: 上下文键值对

### 性能监控

#### performance_tracked(operation_name=None)
性能监控装饰器。

**参数:**
- operation_name (str): 操作名称，可选

#### monitor_performance(operation_name, **extra_data)
性能监控上下文管理器。

**参数:**
- operation_name (str): 操作名称
- **extra_data: 额外数据

#### performance_monitor
全局性能监控器实例，提供各种性能监控方法。

### 数据库集成

#### DatabaseConfig
数据库配置类。

**属性:**
- host (str): 数据库主机
- port (int): 数据库端口
- database (str): 数据库名称
- username (str): 用户名
- password (str): 密码
- schema (str): 模式名称

#### setup_database_logging(**kwargs)
设置数据库日志记录。

**参数:**
- host (str): 数据库主机
- port (int): 数据库端口
- database (str): 数据库名称
- username (str): 用户名
- password (str): 密码
- table_name (str): 日志表名称
- enabled (bool): 是否启用

## 更新日志

### v1.0.0
- 初始版本发布
- 实现基础日志功能
- 添加结构化日志支持
- 实现多目标输出
- 添加上下文追踪
- 实现性能监控
- 添加数据库集成
- 完善文档和示例