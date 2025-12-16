import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import api_router
from app.core.config import settings
from app.core.loguru_logger import configure_logging, get_logger
from app.database import engine
from app.models import Base
from app.middleware.monitoring import SecurityHeadersMiddleware, MetricsMiddleware
from app.middleware.logging import LoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, AuthRateLimitMiddleware
from app.core.exceptions import setup_exception_handlers, ExceptionHandlerMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 应用启动时执行的代码
    # 配置loguru日志系统（统一的日志配置）
    configure_logging(
        level="INFO",
        enable_console=True,
        enable_file=True,
        log_dir="logs",
        app_name="fastapi_app",
        serialize=False  # 确保彩色输出
    )
    
    # 配置其他库的日志级别为WARNING，减少INFO输出
    import logging
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.ERROR)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # 更全面地设置SQLAlchemy日志级别
    logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.dialects").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.orm").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.compiler").setLevel(logging.ERROR)
    
    logger = get_logger("main")
    logger.info("配置日志系统")
    
    logger.info("初始化数据库连接")
    # 创建所有数据库表
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # 检查数据库状态
        from app.utils.status import check_database_connection
        db_status = await check_database_connection()
        
        if db_status["status"] == "connected":
            logger.info("数据库连接成功", 
                        type=db_status['type'], 
                        version=db_status['version'])
        else:
            logger.error("数据库连接失败", 
                        message=db_status.get('message', 'Unknown error'))
            raise Exception(f"Database connection failed: {db_status.get('message', 'Unknown error')}")
    except Exception as e:
        logger.error(f"数据库连接失败: {str(e)}")
        raise
    
    # 初始化RBAC系统
    logger.info("初始化权限系统")
    try:
        from app.database import AsyncSessionLocal
        from app.services.rbac_init import initialize_rbac
        
        # 创建数据库会话
        async with AsyncSessionLocal() as db:
            # 初始化RBAC系统
            init_result = await initialize_rbac(db)
            if init_result["success"]:
                logger.info(
                    "RBAC系统初始化成功",
                    permissions_created=init_result["permissions_created"],
                    roles_created=init_result["roles_created"],
                    admin_created=init_result["admin_created"]
                )
                
                # 如果管理员账号被创建，显示登录信息
                if init_result["admin_created"]:
                    logger.info(
                        "默认管理员账号已创建",
                        username="admin",
                        password="admin123",
                        note="请在生产环境中修改默认密码"
                    )
            else:
                logger.error(
                    "RBAC系统初始化失败",
                    errors=init_result["errors"]
                )
    except Exception as e:
        logger.error(f"RBAC系统初始化异常: {str(e)}")
    
    logger.info("FastAPI RBAC Framework started - version: 1.0.0")
    
    # 检查应用整体状态
    from app.utils.status import check_application_status
    app_status = await check_application_status()
    
    # 显示数据库表状态
    if "database_tables" in app_status:
        tables_status = app_status["database_tables"]
        if tables_status["status"] == "checked":
            tables_found = tables_status["tables_found"]
            total_checked = tables_status["total_checked"]
            logger.info("数据库表检查完成", 
                        tables_found=len(tables_found),
                        total_checked=total_checked,
                        table_list=', '.join(tables_found))
            # 添加更多信息，表明数据库结构完整
            if len(tables_found) == total_checked and total_checked > 0:
                logger.info("数据库结构完整，所有必需的表都已存在")
        else:
            logger.warning("数据库表检查失败", 
                          message=tables_status.get('message', 'Unknown error'))
    
    logger.info("应用初始化完成")
    logger.info("服务器地址: http://0.0.0.0:8000")
    logger.info("API文档: http://0.0.0.0:8000/api/v1/docs")
    logger.info("管理后台: http://0.0.0.0:8000/admin")
    logger.info("FastAPI RBAC Framework 已启动成功")
    
    yield
    # 应用关闭时执行的代码
    logger.info("正在关闭应用")
    logger.info("FastAPI RBAC Framework shutdown - version: 1.0.0")
    logger.info("应用已安全关闭 - version: 1.0.0")


# 创建FastAPI应用实例
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="企业级FastAPI框架，包含RBAC权限管理系统",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc"
)

# 设置全局异常处理器
setup_exception_handlers(app)

# 配置静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 配置中间件（注意异常处理中间件应该放在最外层）
app.add_middleware(ExceptionHandlerMiddleware)
# 添加速率限制中间件
app.add_middleware(AuthRateLimitMiddleware, calls=settings.AUTH_RATE_LIMIT_CALLS, period=settings.AUTH_RATE_LIMIT_PERIOD)
app.add_middleware(RateLimitMiddleware, calls=settings.RATE_LIMIT_CALLS, period=settings.RATE_LIMIT_PERIOD)
app.add_middleware(MetricsMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,  # 从配置文件读取允许的源
    allow_credentials=True,
    allow_methods=settings.ALLOWED_METHODS,  # 从配置文件读取允许的方法
    allow_headers=settings.ALLOWED_HEADERS,  # 从配置文件读取允许的头部
)

# 注册API路由
app.include_router(api_router, prefix=settings.API_V1_STR)

# 注册管理后台路由
from app.admin_routes import create_admin_router
admin_router = create_admin_router(templates)
app.include_router(admin_router, prefix="/admin", tags=["管理后台"])

# 登录页面
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页面"""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "title": "登录",
        "settings": settings
    })

# 根路径
@app.get("/")
async def root():
    return {
        "message": "欢迎使用企业级FastAPI RBAC框架",
        "docs_url": f"{settings.API_V1_STR}/docs",
        "redoc_url": f"{settings.API_V1_STR}/redoc",
        "admin_url": "/admin"
    }


# 健康检查端点
@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# 监控端点
@app.get("/metrics")
async def metrics():
    """获取应用性能指标"""
    # 获取中间件实例
    for middleware in app.user_middleware:
        if hasattr(middleware.cls, '__name__') and 'MetricsMiddleware' in middleware.cls.__name__:
            metrics_instance = middleware.instance
            if hasattr(metrics_instance, 'get_metrics'):
                return metrics_instance.get_metrics()
    
    return {"error": "Metrics not available"}


# 状态端点
@app.get("/status")
async def status():
    """获取应用详细状态"""
    from app.utils.status import check_application_status
    return await check_application_status()