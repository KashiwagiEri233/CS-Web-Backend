import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 添加项目路径到系统路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base  # noqa: E402
from app import models  # noqa: E402,F401  导入所有模型，注册到 metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_db_url() -> str:
    """获取同步数据库 URL（alembic 只需要这一个配置）。

    优先从环境变量读，其次从 Settings（会加载 .env 文件）。
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.replace("+asyncpg", "")

    from app.core.config import settings

    return settings.DATABASE_URL.replace("+asyncpg", "")


def run_migrations_offline() -> None:
    context.configure(
        url=_get_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # 检测列类型变更（如 String(50)->String(100)）
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_db_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # 给迁移连接设锁超时：DDL 拿不到锁时 10 秒内快速失败（抛 LockNotAvailable），
        # 而不是无限等待——否则启动期迁移卡在某个锁上会表现成"日志静默、应用起不来"，
        # 难以排查。失败会明确抛错，由上层 _run_alembic_upgrade 记录。
        connection.exec_driver_sql("SET lock_timeout = '10s'")
        # SQLAlchemy 2.x 的 SET 会隐式开启事务；若不先提交，下面 Alembic 的
        # begin_transaction 会复用该外层事务，而连接关闭时整批 DDL 被回滚，
        # 表面日志显示迁移成功但数据库没有任何表。
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 检测列类型变更（如 String(50)->String(100)）
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
