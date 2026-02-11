"""
FastAPI RBAC Framework 启动脚本

用法:
    python run.py              # 开发模式（热重载）
    python run.py --prod       # 生产模式（多 worker）
    python run.py --port 9000  # 自定义端口
"""

import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="FastAPI RBAC Framework")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="端口号 (默认: 8000)")
    parser.add_argument(
        "--prod", action="store_true", help="生产模式（禁用热重载，4 workers）"
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="生产模式 worker 数量 (默认: 4)"
    )
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.prod,
        workers=args.workers if args.prod else 1,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
