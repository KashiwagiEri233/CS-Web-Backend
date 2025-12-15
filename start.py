"""
FastAPI RBAC Framework 优雅启动脚本
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

import uvicorn

def main():
    """启动FastAPI应用"""
    # 显示启动信息
    print("\n" + "="*60)
    print("      🚀 FastAPI RBAC Framework 启动中...")
    print("="*60)
    print(f"📁 工作目录: {project_root}")
    print(f"🐍 Python环境: {sys.executable}")
    print(f"📝 日志文件: {project_root}/logs/app.log")
    print("-"*60)
    
    try:
        # 启动服务器
        print("2025-12-15 17:20:17 | INFO | startup - 正在启动Web服务器")
        
        # 设置日志级别以减少输出
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info",
            access_log=False,
            use_colors=False,
        )
    except KeyboardInterrupt:
        print("2025-12-15 17:20:17 | INFO | startup - 服务器已停止")
    except Exception as e:
        print(f"2025-12-15 17:20:17 | ERROR | startup - 启动失败: {str(e)}")

if __name__ == "__main__":
    main()