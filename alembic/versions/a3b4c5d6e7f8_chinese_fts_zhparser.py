"""chinese fts zhparser

Revision ID: a3b4c5d6e7f8
Revises: 4f5a6b7c8d9e
Create Date: 2026-08-07

替换 pg_catalog.simple 为中文分词配置（zhparser）。
若 zhparser 扩展不可用则回退到 simple，保证迁移不中断。

前置条件（生产）：
  1. 在 PostgreSQL 服务器安装 zhparser 扩展（编译或包管理器）
  2. 确认 ``SELECT * FROM pg_available_extensions WHERE name='zhparser'`` 有结果
  3. 迁移会自动 CREATE EXTENSION + 建配置 + 重建触发器与索引

若 zhparser 不可用（如本地开发 PG 未装扩展）：
  - 迁移仍会成功，全程回退 pg_catalog.simple（不引用未创建的 chinese 配置）
  - 生产环境请安装 zhparser 扩展后重跑，或设置 FTS_CONFIG=chinese 使查询端一致
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "2a3b4c5d6e7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 探测 zhparser 是否可用：可用则建 `chinese` 配置并使用它；
    # 不可用（如本地开发 PG 未装 zhparser 扩展）则全程回退 pg_catalog.simple。
    # 关键：回退路径绝不引用未创建的 `chinese` 名称，避免
    # `text search configuration name "chinese" must be schema-qualified` 错误。
    op.execute("""
        DO $$
        DECLARE
            v_use_chinese boolean := false;
            v_cfg text;
        BEGIN
            BEGIN
                CREATE EXTENSION IF NOT EXISTS zhparser;
                DROP TEXT SEARCH CONFIGURATION IF EXISTS public.chinese;
                CREATE TEXT SEARCH CONFIGURATION public.chinese (PARSER = zhparser);
                ALTER TEXT SEARCH CONFIGURATION public.chinese
                    ADD MAPPING FOR n,v,a,i,e,l,j WITH simple;
                v_use_chinese := true;
            EXCEPTION WHEN OTHERS THEN
                v_use_chinese := false;
            END;

            IF v_use_chinese THEN
                v_cfg := 'public.chinese';
            ELSE
                v_cfg := 'pg_catalog.simple';
                DROP TEXT SEARCH CONFIGURATION IF EXISTS public.chinese;
            END IF;

            -- 重建 community_posts 触发器
            DROP TRIGGER IF EXISTS tsvector_update_community_posts ON community_posts;
            EXECUTE format(
                'CREATE TRIGGER tsvector_update_community_posts
                 BEFORE INSERT OR UPDATE ON community_posts
                 FOR EACH ROW EXECUTE FUNCTION
                 tsvector_update_trigger(search_vector, %L, title, content_markdown)',
                v_cfg
            );

            -- 重建 users 触发器
            DROP TRIGGER IF EXISTS tsvector_update_users ON users;
            EXECUTE format(
                'CREATE TRIGGER tsvector_update_users
                 BEFORE INSERT OR UPDATE ON users
                 FOR EACH ROW EXECUTE FUNCTION
                 tsvector_update_trigger(search_vector, %L, display_name, username)',
                v_cfg
            );
            EXECUTE format(
                'UPDATE community_posts SET search_vector =
to_tsvector(%L, coalesce(title, '''') || '' '' || coalesce(content_markdown, ''''))',
                v_cfg
            );
            EXECUTE format(
                'UPDATE users SET search_vector =
to_tsvector(%L, coalesce(display_name, '''') || '' '' || coalesce(username, ''''))',
                v_cfg
            );
        END $$;
        """)


def downgrade() -> None:
    # 回退到 pg_catalog.simple
    op.execute(
        "DROP TRIGGER IF EXISTS tsvector_update_community_posts ON community_posts"
    )
    op.execute("DROP TRIGGER IF EXISTS tsvector_update_users ON users")

    op.execute(
        "CREATE TRIGGER tsvector_update_community_posts "
        "BEFORE INSERT OR UPDATE ON community_posts "
        "FOR EACH ROW EXECUTE FUNCTION "
        "tsvector_update_trigger(search_vector, 'pg_catalog.simple', title, content_markdown)"  # noqa: E501
    )
    op.execute(
        "CREATE TRIGGER tsvector_update_users "
        "BEFORE INSERT OR UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION "
        "tsvector_update_trigger(search_vector, 'pg_catalog.simple', display_name, username)"  # noqa: E501
    )

    op.execute(
        "UPDATE community_posts SET search_vector = "
        "to_tsvector('pg_catalog.simple', "
        "coalesce(title, '') || ' ' || coalesce(content_markdown, ''))"
    )
    op.execute(
        "UPDATE users SET search_vector = "
        "to_tsvector('pg_catalog.simple', "
        "coalesce(display_name, '') || ' ' || coalesce(username, ''))"
    )
