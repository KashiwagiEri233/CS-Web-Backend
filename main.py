"""
企业级FastAPI框架启动入口

使用 startup.py 进行优雅启动，此文件保留用于兼容性
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )