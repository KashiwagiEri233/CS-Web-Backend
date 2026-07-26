"""
FastAPI RBAC Framework 启动脚本

用法:
    python run.py                    # 默认开发环境（.env.development），热重载
    python run.py --env 1            # 开发环境（.env.development）
    python run.py --env 2            # 测试环境（.env.test）
    python run.py --prod             # 生产环境（.env）+ 多 worker
    python run.py --port 9000        # 自定义端口
"""

import argparse
import os

import uvicorn

# 环境配置文件映射
ENV_FILES = {
    1: ".env.development",  # 开发环境
    2: ".env.test",  # 测试环境
    3: ".env",  # 生产环境
}


def main():
    parser = argparse.ArgumentParser(description="FastAPI RBAC Framework")
    parser.add_argument(
        "--host",
        default=None,
        help="绑定地址（默认：开发 127.0.0.1，--prod 时 0.0.0.0）",
    )
    parser.add_argument("--port", type=int, default=8000, help="端口号 (默认: 8000)")
    parser.add_argument(
        "--env",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="环境配置: 1=开发(.env.development，默认) 2=测试(.env.test) 3=生产(.env)",
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

    if args.workers < 1:
        parser.error("--workers 必须大于等于 1")
    if args.prod:
        if args.env not in (None, 3):
            parser.error("--prod 只能与 --env 3 一起使用")
        args.env = 3
    elif args.env == 3:
        parser.error("--env 3 必须同时指定 --prod，避免生产配置启用热重载")
    else:
        args.env = args.env or 1

    # 开发模式默认只绑回环（避免把热重载服务暴露到局域网）；生产默认全网卡
    if args.host is None:
        args.host = "0.0.0.0" if args.prod else "127.0.0.1"

    # 根据环境参数设置 ENV_FILE，config.py 的 Settings 会读取该变量
    if args.env is not None:
        env_file = ENV_FILES[args.env]
        os.environ["ENV_FILE"] = env_file
        env_names = {1: "开发", 2: "测试", 3: "生产"}
        # loguru 尚未配置，用 stdout 直接输出启动提示
        import sys

        sys.stdout.write(f"[启动] 使用 {env_names[args.env]} 环境配置: {env_file}\n")
        sys.stdout.flush()

    # 在 uvicorn 启动前配置 loguru 日志系统。
    # 注意：reload 模式下 server 在子进程重新 import 应用，此处配置不会生效于子进程，
    # 故 lifespan 启动时会再调用一次 init_logging（见 app/main.py），保证格式统一。
    from app.core.config import settings
    from app.core.loguru_logger import init_logging

    init_logging(settings)

    # 将 host/port 写入环境变量，供 main.py 的启动日志拼接完整访问 URL。
    # reload 子进程独立 import 应用、拿不到这里的命令行参数，故经环境变量传递。
    os.environ["APP_HOST"] = args.host
    os.environ["APP_PORT"] = str(args.port)
    # worker 数供启动时校验连接池总量（见 database._check_pool_capacity）：
    # 每个 worker 是独立进程、各持一套连接池，总连接数是 worker 数的倍数。
    os.environ["APP_WORKERS"] = str(args.workers if args.prod else 1)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.prod,
        workers=args.workers if args.prod else 1,
        log_config=None,  # 禁用 uvicorn 默认 log_config，由 setup_uvicorn_logging 接管
        access_log=False,
        # 客户端地址只由应用内 TRUSTED_PROXY_CIDRS 解析，避免 Uvicorn 默认
        # 信任转发头而绕过可信代理边界。
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
