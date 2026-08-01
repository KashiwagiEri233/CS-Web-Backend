"""Phase 4 集成测试：论坛/博客/成员/Feed（需要 PostgreSQL）。

覆盖：
1. 版块 CRUD + slug 冲突；
2. 主题：创建/列表筛选/详情/编辑/软删除 + 反范式计数 + 浏览去重；
3. 回复：创建（含楼中楼）/编辑/删除 + reply_count 反范式；
4. 点赞/收藏切换与计数；
5. 审核：隐藏/恢复/置顶/加精/硬删除；
6. 博客：创建/slug 唯一/发布/归档/点赞/系列；
7. 成员与 Feed 聚合；
8. 搜索（关键词 AND 语义）。
"""

import uuid

import pytest
from sqlalchemy import delete

from app.core.exceptions import ConflictException
from app.database import get_session
from app.models.blog import BlogPost
from app.models.forum import ForumCategory
from app.models.user import User
from app.schemas.community import (
    BlogPostInput,
    CategoryInput,
    ReplyInput,
    TopicInput,
    TopicUpdate,
)
from app.services.blog_service import BlogService
from app.services.community_service import CommunityService
from app.services.forum_service import ForumService


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


async def _make_user(db, email: str) -> User:
    user = User(
        username=f"u_{_sfx()}",
        email=email,
        hashed_password="$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyh",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user


async def _cleanup(db, *user_ids: int) -> None:
    from sqlalchemy import text

    for uid in user_ids:
        for table in (
            "forum_mentions",
            "forum_topic_views",
            "forum_likes",
            "forum_favorites",
            "notifications",
        ):
            try:
                await db.execute(
                    text(f"DELETE FROM {table} WHERE user_id=:i"), {"i": uid}
                )
            except Exception:
                pass
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_forum_category_and_topic_flow(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = ForumService(db)
        user = await _make_user(db, f"ft_{sfx}@t.com")
        try:
            # 版块
            cat = await svc.create_category(
                1, CategoryInput(slug=f"cat-{sfx}", name="测试版块", sort_order=1)
            )
            assert cat.topic_count == 0
            with pytest.raises(ConflictException):
                await svc.create_category(
                    1, CategoryInput(slug=f"cat-{sfx}", name="重复")
                )

            # 主题
            topic = await svc.create_topic(
                user.id,
                TopicInput(
                    category_id=cat.id, title=f"主题-{sfx}", content_markdown="内容 abc"
                ),
            )
            assert topic.reply_count == 0

            # 反范式计数
            refreshed = await svc.get_category(cat.id)
            assert refreshed.topic_count == 1

            # 列表 + 搜索
            items, total = await svc.list_topics(search="abc")
            assert total >= 1
            items2, _ = await svc.list_topics(category_id=cat.id)
            assert any(t.id == topic.id for t in items2)

            # 详情 + 点赞状态
            detail = await svc.get_topic(topic.id, current_user_id=user.id)
            assert detail is not None

            # 浏览去重
            assert await svc.record_topic_view(topic.id, user_id=user.id) is True
            assert await svc.record_topic_view(topic.id, user_id=user.id) is False
            detail2 = await svc.get_topic(topic.id)
            assert detail2.view_count == 1

            # 编辑 + 软删除
            updated = await svc.update_topic(
                user.id,
                False,
                topic.id,
                TopicUpdate(title=f"改名-{sfx}", content_markdown="新内容"),
            )
            assert updated.title == f"改名-{sfx}"
            await svc.delete_topic(user.id, False, topic.id)
            assert (await svc.get_category(cat.id)).topic_count == 0
        finally:
            await _cleanup(db, user.id)
            await db.execute(
                delete(ForumCategory).where(ForumCategory.slug.like(f"%{sfx}%"))
            )
            await db.commit()


@pytest.mark.integration
async def test_forum_reply_like_favorite(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = ForumService(db)
        u1 = await _make_user(db, f"fr1_{sfx}@t.com")
        u2 = await _make_user(db, f"fr2_{sfx}@t.com")
        try:
            cat = await svc.create_category(
                1, CategoryInput(slug=f"rc-{sfx}", name="版块")
            )
            topic = await svc.create_topic(
                u1.id,
                TopicInput(
                    category_id=cat.id, title=f"回复主题-{sfx}", content_markdown="正文"
                ),
            )

            # 回复 + 楼中楼
            reply = await svc.create_reply(
                u2.id, topic.id, ReplyInput(content_markdown="回复1")
            )
            nested = await svc.create_reply(
                u1.id,
                topic.id,
                ReplyInput(content_markdown="楼中楼", parent_reply_id=reply.id),
            )
            assert nested.parent_reply_id == reply.id
            topic2 = await svc.get_topic(topic.id)
            assert topic2.reply_count == 2
            nested_list = await svc.list_nested_replies(reply.id)
            assert len(nested_list) == 1

            # 编辑/删除回复
            await svc.update_reply(u2.id, False, reply.id, "改过的回复")
            await svc.delete_reply(u2.id, False, reply.id)
            assert (await svc.reply_repo.get_by_id(reply.id)).status == "deleted"

            # 点赞/收藏
            like1 = await svc.toggle_like(u1.id, "topic", topic.id)
            assert like1["liked"] is True and like1["like_count"] == 1
            like2 = await svc.toggle_like(u1.id, "topic", topic.id)
            assert like2["liked"] is False and like2["like_count"] == 0

            fav = await svc.toggle_favorite(u1.id, topic.id)
            assert fav["favorited"] is True
            favorites, total = await svc.list_user_favorites(u1.id)
            assert total == 1 and favorites[0].id == topic.id
        finally:
            await _cleanup(db, u1.id, u2.id)
            await db.execute(
                delete(ForumCategory).where(ForumCategory.slug.like(f"%{sfx}%"))
            )
            await db.commit()


@pytest.mark.integration
async def test_forum_moderation(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = ForumService(db)
        u = await _make_user(db, f"fm_{sfx}@t.com")
        try:
            cat = await svc.create_category(
                1, CategoryInput(slug=f"mc-{sfx}", name="版块")
            )
            topic = await svc.create_topic(
                u.id,
                TopicInput(
                    category_id=cat.id, title=f"审核主题-{sfx}", content_markdown="x"
                ),
            )
            await svc.hide_topic(1, topic.id, "违规")
            assert (await svc.get_topic(topic.id)).status == "hidden"
            await svc.restore_topic(1, topic.id)
            assert (await svc.get_topic(topic.id)).status == "published"
            await svc.set_topic_pinned(1, topic.id, True)
            assert (await svc.get_topic(topic.id)).is_pinned is True
            await svc.set_topic_featured(1, topic.id, True)
            assert (await svc.get_topic(topic.id)).is_featured is True

            reply = await svc.create_reply(
                u.id, topic.id, ReplyInput(content_markdown="r")
            )
            await svc.hide_reply(1, reply.id, "spam")
            assert (await svc.reply_repo.get_by_id(reply.id)).status == "hidden"
            await svc.restore_reply(1, reply.id)

            await svc.hard_delete_topic(1, topic.id)
            assert (await svc.topic_repo.get_by_id(topic.id)).status == "deleted"
        finally:
            await _cleanup(db, u.id)
            await db.execute(
                delete(ForumCategory).where(ForumCategory.slug.like(f"%{sfx}%"))
            )
            await db.commit()


@pytest.mark.integration
async def test_blog_flow(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = BlogService(db)
        u = await _make_user(db, f"bg_{sfx}@t.com")
        try:
            post = await svc.create_post(
                u.id,
                BlogPostInput(
                    title=f"博客标题-{sfx}",
                    content_markdown="## 章节一 内容",
                    excerpt="摘要",
                    tags=["web"],
                ),
            )
            assert post.slug == f"博客标题-{sfx}".lower().replace("-", "")
            assert post.status == "draft"

            # slug 唯一
            post2 = await svc.create_post(
                u.id,
                BlogPostInput(title=f"博客标题-{sfx}", content_markdown="重复"),
            )
            assert post2.slug != post.slug

            # 发布 → 列表
            await svc.publish_post(post.id)
            posts, total = await svc.list_posts(status="published")
            assert any(p.id == post.id for p in posts)

            # 详情 + 浏览 + 点赞
            fetched = await svc.get_post_by_slug(post.slug, current_user_id=u.id)
            assert fetched.slug == post.slug
            await svc.increment_view(post.id)
            like = await svc.toggle_like(post.id, u.id)
            assert like["liked"] is True and like["like_count"] == 1

            # 归档
            await svc.archive_post(post.id)
            assert (await svc.get_post(post.id)).status == "archived"

            # 系列
            series = await svc.create_series(
                u.id, type("S", (), {"title": f"系列-{sfx}", "description": None})()
            )
            assert series.slug.startswith("系列")
        finally:
            await _cleanup(db, u.id)
            await db.execute(delete(BlogPost).where(BlogPost.title.like(f"%{sfx}%")))
            await db.commit()


@pytest.mark.integration
async def test_members_and_feed(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        forum = ForumService(db)
        u = await _make_user(db, f"mf_{sfx}@t.com")
        try:
            from sqlalchemy import update as sa_update

            await db.execute(
                sa_update(User)
                .where(User.id == u.id)
                .values(display_name=f"成员{sfx}", tech_tags=["web", "ai"])
            )
            await db.commit()

            members = await svc.list_members()
            assert any(m["id"] == u.id and "web" in m["tech_tags"] for m in members)
            members_web = await svc.list_members(tag="web")
            assert any(m["id"] == u.id for m in members_web)
            tags = await svc.list_all_tech_tags()
            assert "web" in tags

            cat = await forum.create_category(
                1, CategoryInput(slug=f"fd-{sfx}", name="版块")
            )
            await forum.create_topic(
                u.id,
                TopicInput(
                    category_id=cat.id, title=f"feed主题-{sfx}", content_markdown="x"
                ),
            )
            feed = await svc.get_feed()
            assert feed["total"] >= 1
            kinds = {i["kind"] for i in feed["items"]}
            assert "member" in kinds
            feed_no_member = await svc.get_feed(exclude_members=True)
            assert all(i["kind"] != "member" for i in feed_no_member["items"])

            stats = await svc.get_feed_stats()
            assert stats["topic_count"] >= 1
        finally:
            await _cleanup(db, u.id)
            await db.execute(
                delete(ForumCategory).where(ForumCategory.slug.like(f"%{sfx}%"))
            )
            await db.commit()
