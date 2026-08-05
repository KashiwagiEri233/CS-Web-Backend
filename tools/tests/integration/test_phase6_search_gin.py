"""Phase 6 集成测试：论坛/成员全文检索（GIN + tsvector）。

覆盖：
1. 帖子搜索命中/未命中/多词 AND 语义；
2. 成员搜索（display_name/username）命中/未命中；
3. EXPLAIN 确认走 GIN Index Scan（全文检索索引生效）。
"""

import uuid

import pytest

from app.database import get_session
from app.models.community import CommunityPost
from app.models.user import User
from app.services.community_service import CommunityService

from .test_phase4_community import _cleanup_users, _make_user, _sfx


@pytest.mark.integration
async def test_post_search_tsvector_hit_and_miss():
    async for db in get_session():
        svc = CommunityService(db)
        author = await _make_user(db, f"{_sfx()}@example.com")
        topic = await svc.create_post(
            author_id=author.id,
            kind="topic",
            title="Rust 异步编程实践指南",
            content_markdown="本文介绍 tokio 运行时与 async/await 的底层原理。",
            category_id=None,
            status="published",
        )
        off = await svc.create_post(
            author_id=author.id,
            kind="topic",
            title="前端工程化",
            content_markdown="webpack 与 vite 构建速度对比。",
            category_id=None,
            status="published",
        )

        # 命中：标题 + 正文组合词
        items, total = await svc.list_posts(kind="topic", search="Rust 异步")
        assert total >= 1 and any(p.id == topic.id for p in items)
        assert not any(p.id == off.id for p in items)

        # 未命中
        items, total = await svc.list_posts(kind="topic", search="区块链 去中心化")
        assert total == 0

        # 多词 AND：必须同时包含 tokio 与 async（同一篇）
        items, total = await svc.list_posts(kind="topic", search="tokio async")
        assert any(p.id == topic.id for p in items)

        await db.delete(topic)
        await db.delete(off)
        await _cleanup_users(db, author.id)
        break


@pytest.mark.integration
async def test_member_search_tsvector():
    async for db in get_session():
        u = await _make_user(db, f"{_sfx()}@example.com")
        u.display_name = "张三丰"
        u.username = "zhang_san"
        db.add(u)
        await db.commit()

        items, total = await svc_member_list(db, search="张三")
        assert total >= 1 and any(x.id == u.id for x in items)

        items, total = await svc_member_list(db, search="zhang")
        assert any(x.id == u.id for x in items)

        items, total = await svc_member_list(db, search="不存在的人")
        assert total == 0

        await _cleanup_users(db, u.id)
        break


async def svc_member_list(db, search):
    from sqlalchemy import or_, select
    from sqlalchemy.dialects.postgresql import TSVECTOR
    from sqlalchemy.sql import text as _text

    from sqlalchemy import func

    ts_query = func.websearch_to_tsquery(_text("'simple'"), search.strip())
    stmt = select(User).where(
        User.deleted_at.is_(None),
        User.search_vector.op("@@")(ts_query),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows, len(rows)


@pytest.mark.integration
async def test_search_uses_gin_index():
    """EXPLAIN 确认搜索走 GIN Index Scan（全文检索索引生效）。"""
    async for db in get_session():
        author = await _make_user(db, f"{_sfx()}@example.com")
        post = await CommunityService(db).create_post(
            author_id=author.id,
            kind="topic",
            title="GIN 索引验证帖",
            content_markdown="postgres tsvector gin index scan check.",
            category_id=None,
            status="published",
        )
        # 触发触发器刷新 search_vector
        await db.refresh(post)

        plan = await db.execute(
            text(
                "EXPLAIN SELECT id FROM community_posts "
                "WHERE search_vector @@ websearch_to_tsquery('simple', 'GIN 索引')"
            )
        )
        plan_text = "\n".join(str(r) for r in plan)
        assert "Index Scan" in plan_text and "gin" in plan_text.lower(), (
            f"期望走 GIN Index Scan，实际：{plan_text}"
        )

        await db.delete(post)
        await _cleanup_users(db, author.id)
        break
