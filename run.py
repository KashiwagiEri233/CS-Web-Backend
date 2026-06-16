"""
FastAPI RBAC Framework 启动脚本

用法:
    python run.py                    # 默认环境（.env），开发模式（热重载）
    python run.py --env 1            # 开发环境（.env.development）
    python run.py --env 2            # 测试环境（.env.test）
    python run.py --env 3            # 生产环境（.env）
    python run.py --env 3 --prod     # 生产环境 + 多 worker
    python run.py --port 9000        # 自定义端口
"""

import argparse
import os

import uvicorn

# 环境配置文件映射
ENV_FILES = {
    1: ".env.development",  # 开发环境
    2: ".env.test",         # 测试环境
    3: ".env",              # 生产环境
}


def main():
    parser = argparse.ArgumentParser(description="FastAPI RBAC Framework")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="端口号 (默认: 8000)")
    parser.add_argument(
        "--env",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="环境配置: 1=开发(.env.development) 2=测试(.env.test) 3=生产(.env)",
    )
    parser.add_argument(
        "--prod",
        action="store_true",
        help="生产模式（禁用热重载，多 workers）",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="生产模式 worker 数量 (默认: 4)"
    )
    args = parser.parse_args()

    # 根据环境参数设置 ENV_FILE，config.py 的 Settings 会读取该变量
    if args.env is not None:
        env_file = ENV_FILES[args.env]
        os.environ["ENV_FILE"] = env_file
        env_names = {1: "开发", 2: "测试", 3: "生产"}
        print(f"[启动] 使用 {env_names[args.env]} 环境配置: {env_file}")

    # 在 uvicorn 启动前配置 loguru 日志系统
    from app.core.config import settings
    from app.core.loguru_logger import (
        configure_logging,
        setup_uvicorn_logging,
        suppress_library_logging,
    )

    configure_logging(
        level=settings.LOG_LEVEL,
        enable_console=settings.LOG_ENABLE_CONSOLE,
        enable_file=settings.LOG_ENABLE_FILE,
        enable_error_file=settings.LOG_ENABLE_ERROR_FILE,
        log_dir=settings.LOG_DIR,
        app_name="fastapi_app",
        serialize=settings.LOG_SERIALIZE,
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        backtrace=settings.LOG_BACKTRACE,
    )
    suppress_library_logging()
    setup_uvicorn_logging()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.prod,
        workers=args.workers if args.prod else 1,
        log_config=None,  # 禁用 uvicorn 默认 log_config，由 setup_uvicorn_logging 接管
        access_log=False,
    )


if __name__ == "__main__":
    main()
