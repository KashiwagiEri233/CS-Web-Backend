"""Phase 6 集成测试：社区/成员全文检索（GIN + tsvector）。

覆盖：
1. 帖子搜索命中/未命中/多词 AND 语义；
2. 成员搜索（display_name/username）命中/未命中；
3. EXPLAIN 确认走 GIN Index Scan（全文检索索引生效）。

注意：测试环境 FTS_CONFIG=simple（无 zhparser），simple 词典按"整词"切分——
中文无分词（"测试用户"是单个 lexeme，搜"测试"不命中），英文按下划线/符号分隔
但整段保留。因此断言一律使用精确词（lexeme），不做子串/前缀假设。
"""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.database import get_session
from app.models.user import User
from app.services.community_post import PostService
from app.services.community_service import CommunityService

from .test_phase4_community import _cleanup_users, _make_user, _sfx


@pytest.mark.integration
async def test_post_search_tsvector_hit_and_miss(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        post_svc = PostService(db)
        author = await _make_user(db, f"{_sfx()}@example.com")
        cat = await svc.create_category(admin_user, f"cat-{sfx}", "测试版块")
        topic = await post_svc.create_post(
            author_id=author.id,
            kind="topic",
            title="Rust 异步编程实践指南",
            content_markdown="本文介绍 tokio 运行时与 async 编程的底层原理。",
            category_id=cat.id,
            status="published",
        )
        off = await post_svc.create_post(
            author_id=author.id,
            kind="topic",
            title="前端工程化",
            content_markdown="webpack 与 vite 构建速度对比。",
            category_id=cat.id,
            status="published",
        )

        # 命中：标题英文精确词
        items, total = await post_svc.list_posts(kind="topic", search="Rust")
        assert total >= 1 and any(p.id == topic.id for p in items)
        assert not any(p.id == off.id for p in items)

        # 命中：正文英文精确词
        items, total = await post_svc.list_posts(kind="topic", search="tokio")
        assert any(p.id == topic.id for p in items)

        # 未命中
        items, total = await post_svc.list_posts(kind="topic", search="区块链")
        assert total == 0

        # 多词 AND：tokio 与 async 必须同篇命中（topic 命中，off 不命中）
        items, total = await post_svc.list_posts(kind="topic", search="tokio async")
        assert any(p.id == topic.id for p in items)
        assert not any(p.id == off.id for p in items)

        await db.delete(topic)
        await db.delete(off)
        await db.delete(cat)
        await _cleanup_users(db, author.id)


@pytest.mark.integration
async def test_member_search_tsvector(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        u = await _make_user(db, f"{_sfx()}@example.com")
        uname = f"zhang_{sfx}"
        u.display_name = "张三丰"
        u.username = uname
        db.add(u)
        await db.commit()

        # 命中：中文展示名精确词（simple 词典无中文分词，整词匹配）
        items, total = await svc_member_list(db, search="张三丰")
        assert total >= 1 and any(x.id == u.id for x in items)

        # 命中：英文用户名精确词
        items, total = await svc_member_list(db, search=uname)
        assert any(x.id == u.id for x in items)

        # 未命中
        items, total = await svc_member_list(db, search="不存在的人")
        assert total == 0

        await _cleanup_users(db, u.id)


async def svc_member_list(db, search):
    from sqlalchemy import func, select
    from sqlalchemy.sql import text as _text

    ts_query = func.websearch_to_tsquery(_text(f"'{settings.FTS_CONFIG}'"), search.strip())
    stmt = select(User).where(
        User.deleted_at.is_(None),
        User.search_vector.op("@@")(ts_query),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows, len(rows)


@pytest.mark.integration
async def test_search_uses_gin_index(integration_db_ready, admin_user):
    """EXPLAIN 确认搜索走 GIN Index Scan（全文检索索引生效）。"""
    sfx = _sfx()
    async with get_session() as db:
        author = await _make_user(db, f"{_sfx()}@example.com")
        cat = await svc_create_category(db, admin_user, f"cat-{sfx}")
        post = await PostService(db).create_post(
            author_id=author.id,
            kind="topic",
            title="GIN 索引验证帖",
            content_markdown="postgres tsvector gin index scan check.",
            category_id=cat.id,
            status="published",
        )
        # 触发触发器刷新 search_vector
        await db.refresh(post)

        # 小表上优化器默认走 Seq Scan，强制关闭以验证 GIN 索引路径可用
        await db.execute(text("SET enable_seqscan = off"))
        plan = await db.execute(
            text(
                "EXPLAIN SELECT id FROM community_posts "
                "WHERE search_vector @@ websearch_to_tsquery('simple', 'GIN 索引')".replace(
                    "'simple'", f"'{settings.FTS_CONFIG}'"
                )
            )
        )
        plan_text = "\n".join(str(r) for r in plan)
        assert "Index Scan" in plan_text and "gin" in plan_text.lower(), (
            f"期望走 GIN Index Scan，实际：{plan_text}"
        )

        await db.delete(post)
        await db.delete(cat)
        await _cleanup_users(db, author.id)


async def svc_create_category(db, admin_id: int, slug: str):
    return await CommunityService(db).create_category(admin_id, slug, "测试版块")
