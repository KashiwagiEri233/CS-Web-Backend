"""社区仓储（community_repo）真实 PostgreSQL 集成测试。

覆盖 ER-02 点名的四类零测试逻辑：CRUD / 分页 / 级联 / 事务回滚；
并顺带锁定：
- ER-01：tags 参数化 JSONB 包含过滤（不再拼 SQL 字面量）；
- ER-16：CommunityInteractionRepository.get_interaction_target_ids 批量查（消 N+1）；
- ER-21：CommunityFollowRepository.bulk_counts / bulk_is_following 批量查（消 N+1）。

本地无法连接数据库时自动 skip；CI 严格模式下直接失败。
清理策略：所有社区行均通过 user_id/author_id 等 FK（ondelete=CASCADE）级联删除，
仅 community_categories.created_by 为 SET NULL，需在删用户前先按 created_by 清掉。
"""

import uuid

import pytest
from sqlalchemy import delete, text

from app.database import get_session
from app.models.community import (
    CommunityCategory,
    CommunityComment,
    CommunityFollow,
    CommunityPost,
    CommunityReaction,
    CommunityReport,
)
from app.models.user import User
from app.repositories.community_repo import (
    CommunityCategoryRepository,
    CommunityCommentRepository,
    CommunityFollowRepository,
    CommunityInteractionRepository,
    CommunityPostRepository,
    CommunityReportRepository,
)

pytestmark = pytest.mark.integration


async def _cleanup_users(db, uids: list[int]) -> None:
    """按 created_by 清分类（SET NULL 不级联），再删用户触发其余表 CASCADE。"""
    await db.execute(
        delete(CommunityCategory).where(CommunityCategory.created_by.in_(uids))
    )
    await db.execute(delete(User).where(User.id.in_(uids)))
    await db.commit()


async def _make_user(db, sfx: str) -> int:
    user = User(
        username=f"itest_comm_u_{sfx}",
        email=f"itest_comm_{sfx}@t.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user.id


# ---------------------------------------------------------------------------
# 1) CRUD —— CommunityCategoryRepository
# ---------------------------------------------------------------------------
async def test_category_crud_and_slug_lookup(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
    try:
        async with get_session() as db:
            repo = CommunityCategoryRepository(db)
            created = await repo.create(
                {
                    "slug": f"itest-cat-{sfx}",
                    "name": f"cat-{sfx}",
                    "description": "i",
                    "created_by": uid,
                }
            )
            cid = created.id
            await db.commit()

            # get_by_id
            assert await repo.get_by_id(cid) is not None
            # get_by_slug（唯一约束路径）
            assert (await repo.get_by_slug(f"itest-cat-{sfx}")) is not None
            assert (await repo.get_by_slug("nope-does-not-exist")) is None
            # list_all 包含新建项
            all_cats = await repo.list_all()
            assert any(c.id == cid for c in all_cats)

            # update
            await repo.update(created, {"name": f"cat-renamed-{sfx}"})
            await db.commit()
            assert (await repo.get_by_id(cid)).name == f"cat-renamed-{sfx}"

            # delete（repo.delete 仅标记，需提交后 get_by_id 才查不到）
            assert await repo.delete(cid) is True
            await db.commit()
            assert await repo.get_by_id(cid) is None
            assert await repo.delete(999999) is False
    finally:
        async with get_session() as db:
            await _cleanup_users(db, [uid])


# ---------------------------------------------------------------------------
# 2) CRUD + 分页 + ER-01 tags 参数化过滤 —— CommunityPostRepository
# ---------------------------------------------------------------------------
async def test_post_create_list_pagination_and_status(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
    try:
        async with get_session() as db:
            repo = CommunityPostRepository(db)
            base = {
                "kind": "topic",
                "author_id": uid,
                "title": "t",
                "content_markdown": "c",
                "status": "published",
            }
            for i in range(5):
                await repo.create({**base, "title": f"p{i}"})
            await db.commit()

            # 分页：author_id 过滤下 total 稳定为 5，skip/limit 切片正确
            page0, total0 = await repo.list_posts(author_id=uid, skip=0, limit=2)
            assert total0 == 5
            assert len(page0) == 2
            page2, total2 = await repo.list_posts(author_id=uid, skip=2, limit=2)
            assert total2 == 5 and len(page2) == 2
            page_last, _ = await repo.list_posts(author_id=uid, skip=4, limit=2)
            assert len(page_last) == 1  # 第 5 条

            # set_status 生效
            first = page0[0]
            await repo.set_status(first.id, "hidden")
            await db.commit()
            assert (await repo.get_by_id(first.id)).status == "hidden"
    finally:
        async with get_session() as db:
            await _cleanup_users(db, [uid])


# ---------------------------------------------------------------------------
# 2.5) ER-01 回归 —— tags 过滤走 JSONB @> 包含（非字符串 LIKE），可实跑且参数化
# ---------------------------------------------------------------------------
async def test_post_tag_filter_jsonb_containment(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
    try:
        async with get_session() as db:
            repo = CommunityPostRepository(db)
            base = {
                "kind": "topic",
                "author_id": uid,
                "title": "t",
                "content_markdown": "c",
                "status": "published",
            }
            for i in range(5):
                tag = "python" if i % 2 == 0 else "golang"
                await repo.create({**base, "title": f"p{i}", "tags": [tag]})
            await db.commit()

            # 参数化 JSONB 包含：python 命中 3 条（i=0,2,4），golang 命中 2 条
            py_posts, py_total = await repo.list_posts(author_id=uid, tag="python")
            assert py_total == 3
            assert all("python" in (p.tags or []) for p in py_posts)
            go_posts, go_total = await repo.list_posts(author_id=uid, tag="golang")
            assert go_total == 2

            # 注入型 tag 不应报错也不应匹配（参数化，绝不拼入 SQL）
            inj_posts, inj_total = await repo.list_posts(
                author_id=uid, tag="python' OR '1'='1"
            )
            assert inj_total == 0
    finally:
        async with get_session() as db:
            await _cleanup_users(db, [uid])


# ---------------------------------------------------------------------------
# 3) 级联 —— 删帖级联删评论（post_id FK ondelete=CASCADE）
# ---------------------------------------------------------------------------
async def test_comment_cascade_on_post_delete(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
    try:
        async with get_session() as db:
            post_repo = CommunityPostRepository(db)
            comment_repo = CommunityCommentRepository(db)
            post = await post_repo.create(
                {
                    "kind": "topic",
                    "author_id": uid,
                    "title": "cascade",
                    "content_markdown": "c",
                    "status": "published",
                }
            )
            pid = post.id
            comment = await comment_repo.create(
                {
                    "post_id": pid,
                    "author_id": uid,
                    "content_markdown": "reply",
                    "status": "published",
                }
            )
            cid = comment.id
            await db.commit()

            assert await comment_repo.get_by_id(cid) is not None
            # 删帖：用原始 SQL DELETE 真实触发 DB 端 FOREIGN KEY ON DELETE CASCADE
            # （ORM db.delete 在本会话会被 SQLAlchemy FK 依赖处理器拦截，不触发级联）
            await db.execute(
                text("DELETE FROM community_posts WHERE id=:p"), {"p": pid}
            )
            await db.commit()
        # 新会话核验评论已被级联删除（避免会话内身份映射残留导致误判）
        async with get_session() as db2:
            assert await CommunityCommentRepository(db2).get_by_id(cid) is None
    finally:
        async with get_session() as db:
            await _cleanup_users(db, [uid])


# ---------------------------------------------------------------------------
# 4) 事务回滚 —— 未提交插入回滚后消失；提交后持久化
# ---------------------------------------------------------------------------
async def test_post_transaction_rollback(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
    try:
        # 回滚路径：flush 后 rollback -> 行不存在
        async with get_session() as db2:
            repo = CommunityPostRepository(db2)
            p = await repo.create(
                {
                    "kind": "topic",
                    "author_id": uid,
                    "title": "rollback",
                    "content_markdown": "c",
                    "status": "published",
                }
            )
            pid = p.id
            await db2.rollback()
        async with get_session() as db3:
            assert await CommunityPostRepository(db3).get_by_id(pid) is None

        # 提交路径：commit -> 行持久化
        async with get_session() as db4:
            repo4 = CommunityPostRepository(db4)
            p2 = await repo4.create(
                {
                    "kind": "topic",
                    "author_id": uid,
                    "title": "committed",
                    "content_markdown": "c",
                    "status": "published",
                }
            )
            pid2 = p2.id
            await db4.commit()
            assert await repo4.get_by_id(pid2) is not None
    finally:
        async with get_session() as db:
            await _cleanup_users(db, [uid])


# ---------------------------------------------------------------------------
# 5) 点赞/收藏 CRUD + ER-16 批量查 —— CommunityInteractionRepository
# ---------------------------------------------------------------------------
async def test_interaction_reaction_favorite_and_batched(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
        post_repo = CommunityPostRepository(db)
        post = await post_repo.create(
            {
                "kind": "topic",
                "author_id": uid,
                "title": "inter",
                "content_markdown": "c",
                "status": "published",
            }
        )
        pid = post.id
        await db.commit()
    try:
        async with get_session() as db:
            repo = CommunityInteractionRepository(db)
            # 点赞
            await repo.add_reaction(uid, "post", pid)
            await db.commit()
            assert (await repo.get_reaction(uid, "post", pid)) is not None
            react = await repo.get_reaction(uid, "post", pid)
            await repo.remove_reaction(react)
            await db.commit()
            assert (await repo.get_reaction(uid, "post", pid)) is None

            # 收藏
            await repo.add_favorite(uid, "post", pid)
            await db.commit()
            assert (await repo.get_favorite(uid, "post", pid)) is not None
            fav = await repo.get_favorite(uid, "post", pid)
            await repo.remove_favorite(fav)
            await db.commit()
            assert (await repo.get_favorite(uid, "post", pid)) is None

            # ER-16：批量取回，空输入短路、命中集合正确
            assert await repo.get_interaction_target_ids(uid, "post", []) == {
                "reaction": set(),
                "favorite": set(),
            }
            await repo.add_reaction(uid, "post", pid)
            await repo.add_favorite(uid, "post", pid)
            await db.commit()
            ids = await repo.get_interaction_target_ids(uid, "post", [pid])
            assert ids == {"reaction": {pid}, "favorite": {pid}}
    finally:
        async with get_session() as db:
            await _cleanup_users(db, [uid])


# ---------------------------------------------------------------------------
# 6) 关注 CRUD + 计数 + ER-21 批量查 —— CommunityFollowRepository
# ---------------------------------------------------------------------------
async def test_follow_create_counts_and_bulk(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        u1 = await _make_user(db, f"{sfx}a")
        u2 = await _make_user(db, f"{sfx}b")
    try:
        async with get_session() as db:
            repo = CommunityFollowRepository(db)
            assert (await repo.get(u1, u2)) is None
            follow = await repo.create(u1, u2)
            await db.commit()
            assert (await repo.get(u1, u2)) is not None

            # 单用户计数
            assert await repo.counts(u1) == (1, 0)
            assert await repo.counts(u2) == (0, 1)
            # 关注列表
            following, ftotal = await repo.list_following(u1, skip=0, limit=10)
            assert ftotal == 1 and following[0].id == u2

            # ER-21：批量计数 / 批量是否已关注
            bc = await repo.bulk_counts([u1, u2])
            assert bc == {u1: (1, 0), u2: (0, 1)}
            assert await repo.bulk_is_following(u1, [u2]) == {u2}
            assert await repo.bulk_is_following(u2, [u1]) == set()
            assert await repo.bulk_is_following(u1, []) == set()
    finally:
        async with get_session() as db:
            await _cleanup_users(db, [u1, u2])


# ---------------------------------------------------------------------------
# 7) 举报 CRUD + 状态流转 —— CommunityReportRepository
# ---------------------------------------------------------------------------
async def test_report_create_list_resolve(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
        post = await CommunityPostRepository(db).create(
            {
                "kind": "topic",
                "author_id": uid,
                "title": "report-target",
                "content_markdown": "c",
                "status": "published",
            }
        )
        pid = post.id
        await db.commit()
    try:
        async with get_session() as db:
            repo = CommunityReportRepository(db)
            report = await repo.create(
                {
                    "reporter_id": uid,
                    "target_type": "post",
                    "target_id": pid,
                    "reason": "spam",
                }
            )
            rid = report.id
            await db.commit()

            pending, ptotal = await repo.list(status="pending")
            assert ptotal >= 1 and any(r.id == rid for r in pending)

            await repo.resolve(report, handled_by=uid, status="resolved")
            await db.commit()
            assert (await repo.get_by_id(rid)).status == "resolved"
            resolved, rtotal = await repo.list(status="resolved")
            assert any(r.id == rid for r in resolved)
    finally:
        async with get_session() as db:
            await _cleanup_users(db, [uid])
