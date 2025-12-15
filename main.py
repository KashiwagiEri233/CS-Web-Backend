"""
企业级FastAPI框架启动入口

使用 startup.py 进行优雅启动，此文件保留用于兼容性
"""
import uvicorn
import logging

# 配置Uvicorn日志级别，减少INFO输出
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.ERROR)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="warning",  # 设置日志级别为warning
        access_log=False,     # 禁用访问日志
    )