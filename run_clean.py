"""
FastAPI RBAC Framework 清洁启动脚本 - 只显示关键信息
"""
import os
import sys
import logging
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 配置环境变量
os.environ.setdefault("PYTHONPATH", str(project_root))

# 设置基本日志配置 - 统一格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# 禁用SQLAlchemy的详细日志
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

import uvicorn

def main():
    """启动FastAPI应用"""
    logger = logging.getLogger("startup")
    
    # 显示启动信息
    print("\n" + "="*60)
    print("      🚀 FastAPI RBAC Framework 启动中...")
    print("="*60)
    logger.info(f"工作目录: {project_root}")
    logger.info(f"Python环境: {sys.executable}")
    logger.info(f"日志文件: {project_root}/logs/app.log")
    print("-"*60)
    
    try:
        # 启动服务器
        logger.info("正在启动Web服务器")
        
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="warning",  # 只显示警告及以上级别的日志
            access_log=False,     # 禁用访问日志
            use_colors=True,
        )
    except KeyboardInterrupt:
        logger.info("服务器已停止")
    except Exception as e:
        logger.error(f"启动失败: {str(e)}")

if __name__ == "__main__":
    main()