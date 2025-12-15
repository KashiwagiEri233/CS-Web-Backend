"""
优雅的FastAPI应用启动脚本
"""
import os
import sys
import logging
import logging.config
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 配置环境变量
os.environ.setdefault("PYTHONPATH", str(project_root))

# 自定义日志配置
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(message)s",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "ERROR", "propagate": False},
        "uvicorn.error": {"level": "ERROR", "propagate": False},
        "uvicorn.access": {"handlers": [], "level": "ERROR", "propagate": False},
        "sqlalchemy.engine": {"handlers": [], "level": "WARNING", "propagate": False},
        "sqlalchemy.pool": {"handlers": [], "level": "WARNING", "propagate": False},
    },
    "root": {"level": "ERROR", "handlers": ["default"]},
}

import uvicorn

def main():
    """
    启动FastAPI应用的主函数
    """
    # 应用自定义日志配置
    logging.config.dictConfig(LOGGING_CONFIG)
    
    # 显示启动标题
    print("\n" + "="*50)
    print("      FastAPI RBAC Framework 启动中...")
    print("="*50)
    
    # 显示系统信息
    print(f"📍 工作目录: {project_root}")
    print(f"🐍 Python 环境: {sys.executable}")
    print(f"📝 日志文件: {project_root}/logs/app.log")
    print("-"*50)
    
    print("🔄 初始化应用组件...")
    
    # 启动服务器
    try:
        print("🌐 启动Web服务器...")
        print("-"*50)
        
        # 创建自定义Uvicorn日志配置，只显示警告和错误
        uvicorn_log_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "()": "uvicorn.logging.DefaultFormatter",
                    "format": "%(levelprefix)s %(message)s",
                    "datefmt": "%H:%M:%S",
                    "use_colors": False,  # 禁用颜色，使用loguru的配置
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": "WARNING", "propagate": False},
                "uvicorn.error": {"level": "ERROR", "propagate": False},
                "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": False},  # 完全禁用访问日志
            },
            "root": {"level": "WARNING", "handlers": ["default"]},
        }
        
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_config=uvicorn_log_config,  # 使用自定义Uvicorn日志配置
            use_colors=True,               # 启用颜色输出
        )
    except KeyboardInterrupt:
        print("\n🛑 服务器已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {str(e)}")

if __name__ == "__main__":
    main()