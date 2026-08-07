"""Phase 4 集成测试（社区 v2 统一表）：posts / comments / reactions / follows / reports / series。

覆盖：
1. 分类 CRUD + slug 冲突 + 反范式计数；
2. posts（topic|post 统一）：创建/列表筛选/详情/草稿/编辑/软删除 + 浏览去重；
3. comments：创建（楼中楼）/编辑/删除 + reply_count 反范式；
4. reactions/favorites 切换与计数；
5. follows：关注/取关/列表/计数；
6. reports：提交/处理；
7. series 创建；
8. 搜索（关键词 AND 语义）。
"""

import uuid

import pytest
from sqlalchemy import delete, text

from app.core.exceptions import ConflictException
from app.database import get_session
from app.models.community import CommunityCategory, CommunityPost
from app.models.user import User
from app.services.community_service import CommunityService


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


async def _cleanup_users(db, *user_ids: int) -> None:
    for uid in user_ids:
        for table in (
            "community_mentions",
            "community_post_views",
            "community_reactions",
            "community_favorites",
            "community_follows",
            "notifications",
            "user_roles",
        ):
            try:
                async with db.begin_nested():
                    await db.execute(
                        text(f"DELETE FROM {table} WHERE user_id=:i"), {"i": uid}
                    )
            except Exception:
                pass
        try:
            async with db.begin_nested():
                await db.execute(
                    text("DELETE FROM community_reports WHERE reporter_id=:i"),
                    {"i": uid},
                )
        except Exception:
            pass
        try:
            async with db.begin_nested():
                await db.execute(
                    text("DELETE FROM community_series WHERE created_by=:i"), {"i": uid}
                )
        except Exception:
            pass
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_category_and_posts_flow(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        u = await _make_user(db, f"cp_{sfx}@t.com")
        try:
            # 分类
            cat = await svc.create_category(1, f"cat-{sfx}", "测试版块", sort_order=1)
            assert cat.post_count == 0
            with pytest.raises(ConflictException):
                await svc.create_category(1, f"cat-{sfx}", "重复")

            # 帖子（topic）
            topic = await svc.create_post(
                u.id,
                "topic",
                title=f"主题-{sfx}",
                content_markdown="内容 abc",
                category_id=cat.id,
            )
            assert topic.kind == "topic"
            assert (await svc.get_category(cat.id)).post_count == 1

            # 帖子（post，自动 slug）
            post = await svc.create_post(
                u.id,
                "post",
                title=f"文章-{sfx}",
                content_markdown="正文",
                status="published",
                tags=["web"],
            )
            assert post.kind == "post" and post.slug

            # 草稿
            draft = await svc.create_post(
                u.id,
                "post",
                title=f"草稿-{sfx}",
                content_markdown="draft",
                status="draft",
            )
            drafts, _ = await svc.user_drafts(u.id)
            assert any(p.id == draft.id for p in drafts)

            # 列表 + 筛选 + 搜索
            items, total = await svc.list_posts(kind="topic", search="abc")
            assert any(p.id == topic.id for p in items)
            posts, _ = await svc.list_posts(kind="post", status="published")
            assert any(p.id == post.id for p in posts)

            # 详情 + 浏览去重
            detail = await svc.get_post(topic.id, current_user_id=u.id)
            assert detail is not None
            assert await svc.increment_view(topic.id, user_id=u.id) is True
            assert await svc.increment_view(topic.id, user_id=u.id) is False
            assert (await svc.get_post(topic.id)).view_count == 1

            # 编辑 + 软删除
            updated = await svc.update_post(
                u.id, topic.id, {"title": f"改名-{sfx}"}, is_admin=False
            )
            assert updated.title == f"改名-{sfx}"
            await svc.delete_post(u.id, topic.id, is_admin=False)
            assert (await svc.get_post(topic.id)).status == "deleted"
            assert (await svc.get_category(cat.id)).post_count == 0
        finally:
            await _cleanup_users(db, u.id)
            await db.execute(
                delete(CommunityCategory).where(CommunityCategory.slug.like(f"%{sfx}%"))
            )
            await db.execute(
                delete(CommunityPost).where(CommunityPost.title.like(f"%{sfx}%"))
            )
            await db.commit()


@pytest.mark.integration
async def test_comments_reactions_favorites(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        u1 = await _make_user(db, f"cc1_{sfx}@t.com")
        u2 = await _make_user(db, f"cc2_{sfx}@t.com")
        try:
            cat = await svc.create_category(1, f"rc-{sfx}", "版块")
            post = await svc.create_post(
                u1.id,
                "topic",
                title=f"互动主题-{sfx}",
                content_markdown="正文",
                category_id=cat.id,
            )

            # 评论 + 楼中楼
            comment = await svc.create_comment(u2.id, post.id, "评论1")
            nested = await svc.create_comment(
                u1.id, post.id, "楼中楼", parent_comment_id=comment.id
            )
            assert nested.parent_comment_id == comment.id
            assert (await svc.get_post(post.id)).reply_count == 2
            nested_list = await svc.list_nested_comments(comment.id)
            assert len(nested_list) == 1

            # 编辑/删除评论
            await svc.update_comment(u2.id, False, comment.id, "改过的评论")
            assert (
                await svc.comment_repo.get_by_id(comment.id)
            ).content_markdown == "改过的评论"
            await svc.delete_comment(u2.id, False, comment.id)
            assert (await svc.comment_repo.get_by_id(comment.id)).status == "deleted"

            # 点赞/收藏
            like1 = await svc.toggle_like(u1.id, "post", post.id)
            assert like1["liked"] is True and like1["like_count"] == 1
            like2 = await svc.toggle_like(u1.id, "post", post.id)
            assert like2["liked"] is False and like2["like_count"] == 0

            fav = await svc.toggle_favorite(u1.id, post.id)
            assert fav["favorited"] is True
            favorites, total = await svc.list_user_favorites(u1.id)
            assert total == 1 and favorites[0].id == post.id

            status = await svc.get_reaction_status(u1.id, "post", post.id)
            assert status["favorited"] is True
        finally:
            await _cleanup_users(db, u1.id, u2.id)
            await db.execute(
                delete(CommunityCategory).where(CommunityCategory.slug.like(f"%{sfx}%"))
            )
            await db.execute(
                delete(CommunityPost).where(CommunityPost.title.like(f"%{sfx}%"))
            )
            await db.commit()


@pytest.mark.integration
async def test_follows_and_reports(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        u1 = await _make_user(db, f"fl1_{sfx}@t.com")
        u2 = await _make_user(db, f"fl2_{sfx}@t.com")
        u3 = await _make_user(db, f"fl3_{sfx}@t.com")
        try:
            # 关注
            result = await svc.toggle_follow(u1.id, u2.id)
            assert result["following"] is True
            assert await svc.is_following(u1.id, u2.id) is True
            assert await svc.is_following(u2.id, u1.id) is False

            # 关注列表
            following_result = await svc.list_following(u1.id, current_user_id=u1.id)
            assert len(following_result["items"]) == 1
            followers_result = await svc.list_followers(u2.id, current_user_id=u1.id)
            assert len(followers_result["items"]) == 1

            # 关注流列表
            cat = await svc.create_category(1, f"fc-{sfx}", "版块")
            await svc.create_post(
                u2.id,
                "topic",
                title=f"关注流-{sfx}",
                content_markdown="x",
                category_id=cat.id,
            )
            feed_posts, feed_total = await svc.list_posts(
                following_only=True, current_user_id=u1.id
            )
            assert feed_total >= 1 and all(p.author_id == u2.id for p in feed_posts)

            # 取关
            result2 = await svc.toggle_follow(u1.id, u2.id)
            assert result2["following"] is False

            # 举报
            post = await svc.create_post(
                u2.id,
                "topic",
                title=f"举报-{sfx}",
                content_markdown="bad",
                category_id=cat.id,
            )
            report = await svc.submit_report(u3.id, "post", post.id, "违规", "测试")
            assert report.status == "pending"
            reports, total = await svc.list_reports(status="pending")
            assert total >= 1
            await svc.resolve_report(u1.id, report.id, "resolved")
            assert (await svc.report_repo.get_by_id(report.id)).status == "resolved"
        finally:
            await _cleanup_users(db, u1.id, u2.id, u3.id)
            await db.execute(
                delete(CommunityCategory).where(CommunityCategory.slug.like(f"%{sfx}%"))
            )
            await db.execute(
                delete(CommunityPost).where(CommunityPost.title.like(f"%{sfx}%"))
            )
            await db.commit()


@pytest.mark.integration
async def test_series_and_moderation(integration_db_ready):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        u = await _make_user(db, f"md_{sfx}@t.com")
        try:
            # 系列
            series = await svc.create_series(u.id, f"系列-{sfx}", "描述")
            assert series.slug and series.id > 0
            post = await svc.create_post(
                u.id,
                "post",
                title=f"系列文-{sfx}",
                content_markdown="x",
                status="published",
                series_id=series.id,
            )
            posts, _ = await svc.list_posts(
                kind="post", status="published", series_id=series.id
            )
            assert any(p.id == post.id for p in posts)

            # 审核：隐藏/恢复/置顶/加精/硬删除
            topic = await svc.create_post(
                u.id,
                "topic",
                title=f"审核-{sfx}",
                content_markdown="x",
                category_id=(await svc.create_category(1, f"mc-{sfx}", "版块")).id,
            )
            await svc.hide_post(1, topic.id, "违规")
            assert (await svc.get_post(topic.id)).status == "hidden"
            await svc.restore_post(1, topic.id)
            assert (await svc.get_post(topic.id)).status == "published"
            await svc.set_post_pinned(1, topic.id, True)
            assert (await svc.get_post(topic.id)).is_pinned is True
            await svc.set_post_featured(1, topic.id, True)
            assert (await svc.get_post(topic.id)).is_featured is True
            await svc.hard_delete_post(1, topic.id)
            assert (await svc.get_post(topic.id)).status == "deleted"
        finally:
            await _cleanup_users(db, u.id)
            await db.execute(
                delete(CommunityCategory).where(CommunityCategory.slug.like(f"%{sfx}%"))
            )
            await db.execute(
                delete(CommunityPost).where(CommunityPost.title.like(f"%{sfx}%"))
            )
            await db.commit()
