"""
高级日志系统使用示例
展示如何使用新的日志系统进行各种日志记录和监控
"""

import asyncio
import time
from typing import Dict, Any

import sys
import os

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import (
    # 基础日志
    get_logger, set_logging_context, clear_logging_context,
    LoggingContextManager, bind_context,
    
    # 结构化日志配置
    configure_logging, start_logging_system, stop_logging_system,
    
    # 上下文追踪
    get_request_id, get_trace_id, get_user_id,
    
    # 性能监控
    performance_monitor, slow_query_monitor,
    monitor_performance, monitor_performance_async,
    performance_traced, slow_query_tracked,
    
    # FastAPI集成
    integrate_with_fastapi,
    
    # 处理器
    create_colored_console_handler, setup_log_files
)

# 基础使用示例
def basic_usage_example():
    """基础使用示例"""
    print("=== 基础日志记录示例 ===")
    
    # 获取日志记录器
    logger = get_logger("example")
    
    # 基础日志记录
    logger.info("这是一条信息日志", user_id=123, action="login")
    logger.warning("这是一条警告日志", module="auth", error_code=401)
    logger.error("这是一条错误日志", error="Invalid credentials", ip="192.168.1.1")
    
    print("基础日志记录完成\n")


def context_usage_example():
    """上下文使用示例"""
    print("=== 上下文日志示例 ===")
    
    # 获取日志记录器
    logger = get_logger("context_example")
    
    # 设置全局上下文
    set_logging_context(request_id="req-123", user_id=456, service="api")
    
    # 这些日志会自动包含全局上下文
    logger.info("处理用户请求", endpoint="/api/users")
    logger.debug("验证用户权限", resource="users", action="read")
    
    # 使用上下文管理器
    with LoggingContextManager(operation="data_processing", batch_id="batch-789"):
        logger.info("开始处理数据", record_count=100)
        
        # 创建绑定上下文的日志器
        task_logger = logger.bind(task="validation", step=1)
        task_logger.info("验证数据格式", valid_count=95, invalid_count=5)
        
        task_logger = task_logger.bind(step=2)
        task_logger.info("转换数据格式")
        
        logger.info("数据处理完成")
    
    # 清空上下文
    clear_logging_context()
    
    print("上下文日志示例完成\n")


def performance_monitoring_example():
    """性能监控示例"""
    print("=== 性能监控示例 ===")
    
    # 配置性能监控
    from app.core.logging import setup_performance_monitoring
    setup_performance_monitoring(
        enabled=True,
        slow_query_threshold_ms=500.0  # 500ms阈值
    )
    
    # 设置性能阈值
    performance_monitor.set_threshold(
        "user_api_call",
        warning_threshold_ms=500.0,
        error_threshold_ms=1000.0,
        sample_rate=1.0
    )
    
    # 获取日志记录器
    logger = get_logger("performance_example")
    
    # 使用装饰器监控函数性能
    @performance_tracked("slow_function")
    def slow_function():
        time.sleep(0.6)  # 模拟慢操作
        return "操作结果"
    
    # 使用上下文管理器监控代码块性能
    with monitor_performance("database_query", query_type="SELECT", table="users"):
        time.sleep(0.7)  # 模拟慢查询
        logger.info("查询完成", result_count=50)
    
    # 调用被监控的函数
    result = slow_function()
    logger.info("函数执行结果", result=result)
    
    # 查看性能统计
    stats = performance_monitor.get_statistics()
    print("性能统计:", stats)
    
    # 查看告警
    alerts = performance_monitor.get_alerts()
    print("性能告警:", alerts)
    
    print("性能监控示例完成\n")


def database_query_example():
    """数据库查询监控示例"""
    print("=== 数据库查询监控示例 ===")
    
    # 获取日志记录器
    logger = get_logger("database_example")
    
    # 使用装饰器监控数据库查询
    @slow_query_tracked("user_query", database="app_db", table="users")
    def fetch_users():
        time.sleep(0.8)  # 模拟慢查询
        return [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    
    # 使用上下文管理器监控数据库查询
    with monitor_database_query(
        "SELECT * FROM products WHERE price > 100",
        database="app_db",
        table="products",
        min_price=100
    ):
        time.sleep(0.6)  # 模拟慢查询
        logger.info("产品查询完成", count=25)
    
    # 调用被监控的查询函数
    users = fetch_users()
    logger.info("用户查询结果", users=users)
    
    # 查看慢查询记录
    slow_queries = slow_query_monitor.get_slow_queries()
    print("慢查询记录:", slow_queries)
    
    print("数据库查询监控示例完成\n")


async def async_logging_example():
    """异步日志示例"""
    print("=== 异步日志示例 ===")
    
    from app.core.logging import get_async_logger
    
    # 获取异步日志记录器
    async_logger = get_async_logger("async_example")
    
    # 启动异步日志记录器
    await async_logger.start()
    
    # 异步记录日志
    await async_logger.info("异步信息日志", async_operation=True)
    await async_logger.warning("异步警告日志", warning_type="timeout")
    await async_logger.error("异步错误日志", error="AsyncException")
    
    # 使用异步性能监控
    async with monitor_performance_async("async_operation", type="background_task"):
        await asyncio.sleep(0.5)  # 模拟异步操作
        await async_logger.info("异步操作完成")
    
    # 停止异步日志记录器
    await async_logger.stop()
    
    print("异步日志示例完成\n")


def advanced_configuration_example():
    """高级配置示例"""
    print("=== 高级配置示例 ===")
    
    from app.core.logging import configure_logging, DatabaseConfig
    
    # 配置控制台和文件日志
    configure_logging(
        level="INFO",
        enable_console=True,
        enable_file=True,
        log_dir="example_logs",
        app_name="example_app",
        console_format="colored",
        file_max_size_mb=5,
        file_backup_count=3,
        enable_performance=True,
        performance_thresholds={
            "api_request": {"warning": 500.0, "error": 1000.0, "sample_rate": 1.0},
            "database_query": {"warning": 200.0, "error": 500.0, "sample_rate": 0.5}
        }
    )
    
    # 配置数据库日志（模拟）
    db_config = DatabaseConfig(
        host="localhost",
        port=5432,
        database="example_logs",
        username="postgres",
        password="password"
    )
    
    # 获取日志记录器
    logger = get_logger("advanced_example")
    
    logger.info("高级配置日志", config_type="console+file+performance")
    
    # 创建自定义处理器
    from app.core.logging.handlers import create_simple_console_handler
    simple_handler = create_simple_console_handler("[CUSTOM] ", level="DEBUG")
    logger.addHandler(simple_handler)
    
    print("高级配置示例完成\n")


def integration_with_existing_code_example():
    """与现有代码集成示例"""
    print("=== 现有代码集成示例 ===")
    
    # 导入兼容函数
    from app.core.logging import (
        log_user_action, log_security_event, 
        log_exception, log_request_response
    )
    
    # 使用兼容的日志函数
    log_user_action(123, "login", "auth", {"ip": "192.168.1.1", "user_agent": "Chrome"})
    log_security_event("failed_login", 123, {"reason": "invalid_password"})
    
    print("现有代码集成示例完成\n")


def fastapi_integration_example():
    """FastAPI集成示例"""
    print("=== FastAPI集成示例 ===")
    
    from fastapi import FastAPI, Request
    from app.core.logging import integrate_with_fastapi
    
    # 创建FastAPI应用
    app = FastAPI(title="日志系统示例")
    
    # 集成日志系统
    app = integrate_with_fastapi(
        app,
        level="INFO",
        enable_console=True,
        enable_file=True,
        enable_performance=True,
        log_dir="fastapi_logs"
    )
    
    # 添加API路由
    @app.get("/api/users")
    async def get_users():
        logger = get_logger("api.users")
        logger.info("获取用户列表", endpoint="/api/users")
        return [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    
    @app.post("/api/users")
    async def create_user(user_data: dict):
        logger = get_logger("api.users")
        logger.info("创建用户", user_data=user_data)
        return {"id": 3, **user_data}
    
    print("FastAPI集成配置完成\n")
    print("运行命令: uvicorn examples.logging_usage:app --reload")
    print("然后访问 http://localhost:8000/api/users 查看日志")


def custom_alert_handler_example():
    """自定义告警处理器示例"""
    print("=== 自定义告警处理器示例 ===")
    
    # 自定义告警处理器
    def custom_alert_handler(alert):
        print(f"🚨 性能告警: {alert.operation_name} 耗时 {alert.duration_ms:.2f}ms ({alert.threshold_type})")
        if alert.request_id:
            print(f"   请求ID: {alert.request_id}")
        if alert.trace_id:
            print(f"   追踪ID: {alert.trace_id}")
        print("-" * 50)
    
    def custom_slow_query_handler(slow_query):
        print(f"🐌 慢查询: {slow_query['query']} 耗时 {slow_query['duration_ms']:.2f}ms")
        if slow_query.get('table'):
            print(f"   表: {slow_query['table']}")
        print("-" * 50)
    
    # 注册告警处理器
    performance_monitor.add_alert_handler(custom_alert_handler)
    slow_query_monitor.add_alert_handler(custom_slow_query_handler)
    
    # 配置监控
    from app.core.logging import setup_performance_monitoring
    setup_performance_monitoring(enabled=True, slow_query_threshold_ms=300.0)
    
    # 设置性能阈值
    performance_monitor.set_threshold(
        "test_operation",
        warning_threshold_ms=300.0,
        error_threshold_ms=500.0
    )
    
    # 获取日志记录器
    logger = get_logger("alert_example")
    
    # 触发性能告警
    with monitor_performance("test_operation"):
        time.sleep(0.4)  # 模拟慢操作
        logger.info("测试操作完成")
    
    # 触发慢查询告警
    with monitor_database_query("SELECT * FROM large_table", table="large_table"):
        time.sleep(0.5)  # 模拟慢查询
        logger.info("查询完成")
    
    print("自定义告警处理器示例完成\n")


async def database_integration_example():
    """数据库集成示例"""
    print("=== 数据库集成示例 ===")
    
    from app.core.logging import setup_database_logging, DatabaseConfig
    
    try:
        # 配置数据库日志（注意：这里需要实际数据库连接）
        db_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="fastapi_logs",
            username="postgres",
            password="password"
        )
        
        # 启动数据库日志记录
        await setup_database_logging(
            host=db_config.host,
            port=db_config.port,
            database=db_config.database,
            username=db_config.username,
            password=db_config.password,
            table_name="application_logs",
            enabled=True
        )
        
        # 获取日志记录器
        logger = get_logger("database_example")
        
        # 记录一些日志（这些日志会被存储到数据库）
        for i in range(5):
            logger.info(
                f"数据库日志测试 {i+1}",
                test_case="database_logging",
                iteration=i+1,
                timestamp=time.time()
            )
        
        print("数据库日志记录完成（注意：需要实际数据库连接）")
        
    except Exception as e:
        print(f"数据库集成示例失败（预期行为）: {e}")
        print("请确保PostgreSQL服务器已启动并配置正确")
    
    print("数据库集成示例完成\n")


async def main():
    """主函数，运行所有示例"""
    print("高级日志系统使用示例\n")
    
    # 基础示例
    basic_usage_example()
    context_usage_example()
    performance_monitoring_example()
    database_query_example()
    
    # 异步示例
    await async_logging_example()
    
    # 高级示例
    advanced_configuration_example()
    integration_with_existing_code_example()
    custom_alert_handler_example()
    fastapi_integration_example()
    
    # 数据库示例
    await database_integration_example()
    
    print("所有示例运行完成！")
    
    # 清理资源
    await stop_logging_system()


if __name__ == "__main__":
    asyncio.run(main())