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
from app.services import view_count
from app.services.community_comment import CommentService
from app.services.community_interaction import FavoriteService, ReactionService
from app.services.community_post import PostService
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
async def test_category_and_posts_flow(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        post_svc = PostService(db)
        u = await _make_user(db, f"cp_{sfx}@t.com")
        try:
            # 分类
            cat = await svc.create_category(admin_user, f"cat-{sfx}", "测试版块", sort_order=1)
            assert cat.post_count == 0
            with pytest.raises(ConflictException):
                await svc.create_category(admin_user, f"cat-{sfx}", "重复")

            # 帖子（topic）
            topic = await post_svc.create_post(
                u.id,
                "topic",
                title=f"主题-{sfx}",
                content_markdown="内容 abc",
                category_id=cat.id,
            )
            assert topic.kind == "topic"
            assert (await svc.get_category(cat.id)).post_count == 1

            # 帖子（post，自动 slug）
            post = await post_svc.create_post(
                u.id,
                "post",
                title=f"文章-{sfx}",
                content_markdown="正文",
                status="published",
                tags=["web"],
            )
            assert post.kind == "post" and post.slug

            # 草稿
            draft = await post_svc.create_post(
                u.id,
                "post",
                title=f"草稿-{sfx}",
                content_markdown="draft",
                status="draft",
            )
            drafts, _ = await post_svc.user_drafts(u.id)
            assert any(p.id == draft.id for p in drafts)

            # 列表 + 筛选 + 搜索
            items, total = await post_svc.list_posts(kind="topic", search="abc")
            assert any(p.id == topic.id for p in items)
            posts, _ = await post_svc.list_posts(kind="post", status="published")
            assert any(p.id == post.id for p in posts)

            # 详情 + 浏览去重
            detail = await post_svc.get_post(topic.id, current_user_id=u.id)
            assert detail is not None
            assert await post_svc.increment_view(topic.id, user_id=u.id) is True
            assert await post_svc.increment_view(topic.id, user_id=u.id) is False
            # ER-22：view_count 改 Redis 计数 + 异步落库（最终一致），
            # 此处白盒强制 flush 后断言最终值，验证落库路径正确。
            # 注：_flush_once 用独立 session 落库，原 session identity map 仍缓存旧值，
            # 须先 refresh 再读。
            await view_count._flush_once()
            await db.refresh(topic)
            assert (await post_svc.get_post(topic.id)).view_count == 1

            # 编辑 + 软删除
            updated = await post_svc.update_post(
                u.id, topic.id, {"title": f"改名-{sfx}"}, is_admin=False
            )
            assert updated.title == f"改名-{sfx}"
            await post_svc.delete_post(u.id, topic.id, is_admin=False)
            assert (await post_svc.get_post(topic.id)).status == "deleted"
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
async def test_comments_reactions_favorites(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        post_svc = PostService(db)
        comment_svc = CommentService(db)
        reaction = ReactionService(db)
        favorite = FavoriteService(db)
        u1 = await _make_user(db, f"cc1_{sfx}@t.com")
        u2 = await _make_user(db, f"cc2_{sfx}@t.com")
        try:
            cat = await svc.create_category(admin_user, f"rc-{sfx}", "版块")
            post = await post_svc.create_post(
                u1.id,
                "topic",
                title=f"互动主题-{sfx}",
                content_markdown="正文",
                category_id=cat.id,
            )

            # 评论 + 楼中楼
            comment = await comment_svc.create_comment(u2.id, post.id, "评论1")
            nested = await comment_svc.create_comment(
                u1.id, post.id, "楼中楼", parent_comment_id=comment.id
            )
            assert nested.parent_comment_id == comment.id
            assert (await post_svc.get_post(post.id)).reply_count == 2
            nested_list = await comment_svc.list_nested_comments(comment.id)
            assert len(nested_list) == 1

            # 编辑/删除评论
            await comment_svc.update_comment(u2.id, False, comment.id, "改过的评论")
            assert (
                await comment_svc.comment_repo.get_by_id(comment.id)
            ).content_markdown == "改过的评论"
            await comment_svc.delete_comment(u2.id, False, comment.id)
            assert (
                await comment_svc.comment_repo.get_by_id(comment.id)
            ).status == "deleted"

            # 点赞/收藏
            like1 = await reaction.toggle_like(u1.id, "post", post.id)
            assert like1["liked"] is True and like1["like_count"] == 1
            like2 = await reaction.toggle_like(u1.id, "post", post.id)
            assert like2["liked"] is False and like2["like_count"] == 0

            fav = await favorite.toggle_favorite(u1.id, post.id)
            assert fav["favorited"] is True
            favorites, total = await post_svc.list_user_favorites(u1.id)
            assert total == 1 and favorites[0].id == post.id

            status = await reaction.get_reaction_status(u1.id, "post", post.id)
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
async def test_follows_and_reports(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        post_svc = PostService(db)
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
            cat = await svc.create_category(admin_user, f"fc-{sfx}", "版块")
            await post_svc.create_post(
                u2.id,
                "topic",
                title=f"关注流-{sfx}",
                content_markdown="x",
                category_id=cat.id,
            )
            feed_posts, feed_total = await post_svc.list_posts(
                following_only=True, current_user_id=u1.id
            )
            assert feed_total >= 1 and all(p.author_id == u2.id for p in feed_posts)

            # 取关
            result2 = await svc.toggle_follow(u1.id, u2.id)
            assert result2["following"] is False

            # 举报
            post = await post_svc.create_post(
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
async def test_series_and_moderation(integration_db_ready, admin_user):
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        post_svc = PostService(db)
        u = await _make_user(db, f"md_{sfx}@t.com")
        try:
            # 系列
            series = await svc.create_series(u.id, f"系列-{sfx}", "描述")
            assert series.slug and series.id > 0
            post = await post_svc.create_post(
                u.id,
                "post",
                title=f"系列文-{sfx}",
                content_markdown="x",
                status="published",
                series_id=series.id,
            )
            posts, _ = await post_svc.list_posts(
                kind="post", status="published", series_id=series.id
            )
            assert any(p.id == post.id for p in posts)

            # 审核：隐藏/恢复/置顶/加精/硬删除
            topic = await post_svc.create_post(
                u.id,
                "topic",
                title=f"审核-{sfx}",
                content_markdown="x",
                category_id=(await svc.create_category(admin_user, f"mc-{sfx}", "版块")).id,
            )
            await post_svc.hide_post(admin_user, topic.id, "违规")
            assert (await post_svc.get_post(topic.id)).status == "hidden"
            await post_svc.restore_post(admin_user, topic.id)
            assert (await post_svc.get_post(topic.id)).status == "published"
            await post_svc.set_post_pinned(admin_user, topic.id, True)
            assert (await post_svc.get_post(topic.id)).is_pinned is True
            await post_svc.set_post_featured(admin_user, topic.id, True)
            assert (await post_svc.get_post(topic.id)).is_featured is True
            await post_svc.hard_delete_post(admin_user, topic.id)
            assert (await post_svc.get_post(topic.id)).status == "deleted"
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
async def test_enrich_posts_interaction_flags_batched(integration_db_ready):
    """ER-16：_enrich_posts 用合并批量查询标记点赞/收藏，2N→2 且标记正确。"""
    sfx = _sfx()
    async with get_session() as db:
        svc = PostService(db)
        reaction = ReactionService(db)
        favorite = FavoriteService(db)
        viewer = await _make_user(db, f"er16v_{sfx}@t.com")
        author = await _make_user(db, f"er16a_{sfx}@t.com")
        try:
            posts = []
            for i in range(3):
                posts.append(
                    await svc.create_post(
                        author.id,
                        "post",
                        title=f"ER16-{sfx}-{i}",
                        content_markdown="x",
                        status="published",
                    )
                )

            # viewer 仅点赞第 0 篇、收藏第 1 篇，第 2 篇无任何互动
            await reaction.toggle_like(viewer.id, "post", posts[0].id)
            await favorite.toggle_favorite(viewer.id, posts[1].id)

            await svc._enrich_posts(posts, current_user_id=viewer.id)
            assert posts[0].is_liked_by_me is True
            assert posts[0].is_favorited_by_me is False
            assert posts[1].is_liked_by_me is False
            assert posts[1].is_favorited_by_me is True
            assert posts[2].is_liked_by_me is False
            assert posts[2].is_favorited_by_me is False

            # 未登录分支：全部 False，且不触发任何 interaction 查询
            await svc._enrich_posts(posts)
            for p in posts:
                assert p.is_liked_by_me is False
                assert p.is_favorited_by_me is False
        finally:
            await _cleanup_users(db, viewer.id, author.id)
            await db.execute(
                delete(CommunityPost).where(CommunityPost.title.like(f"%{sfx}%"))
            )
            await db.commit()


@pytest.mark.integration
async def test_format_follow_users_batched_counts(integration_db_ready):
    """ER-21：_format_follow_users 批量聚合关注计数/关系，N+1→常量查询且数据正确。"""
    sfx = _sfx()
    async with get_session() as db:
        svc = CommunityService(db)
        u1 = await _make_user(db, f"er21v_{sfx}@t.com")  # 观察视角
        u2 = await _make_user(db, f"er21a_{sfx}@t.com")
        u3 = await _make_user(db, f"er21b_{sfx}@t.com")
        u4 = await _make_user(db, f"er21c_{sfx}@t.com")
        try:
            # u1 关注 u2、u3；u2 关注 u3；u4 关注 u1
            await svc.toggle_follow(u1.id, u2.id)
            await svc.toggle_follow(u1.id, u3.id)
            await svc.toggle_follow(u2.id, u3.id)
            await svc.toggle_follow(u4.id, u1.id)

            # list_following：u1 关注的人（u2, u3）
            following = await svc.list_following(u1.id, current_user_id=u1.id)
            assert following["total"] == 2
            by_id = {it["id"]: it for it in following["items"]}
            assert by_id[u2.id]["following_count"] == 1  # u2 关注 u3
            assert by_id[u2.id]["follower_count"] == 1  # u1 关注 u2
            assert by_id[u2.id]["is_following"] is True
            assert by_id[u3.id]["following_count"] == 0  # u3 不关注任何人
            assert by_id[u3.id]["follower_count"] == 2  # u1、u2 关注 u3
            assert by_id[u3.id]["is_following"] is True

            # list_followers：关注 u1 的人（u4）
            followers = await svc.list_followers(u1.id, current_user_id=u1.id)
            assert followers["total"] == 1
            f = followers["items"][0]
            assert f["id"] == u4.id
            assert f["following_count"] == 1  # u4 关注 u1
            assert f["follower_count"] == 0
            assert f["is_following"] is False  # u1 未关注 u4

            # 未登录（current_user_id=None）分支：计数仍正确，is_following 全 False
            following_anon = await svc.list_following(u1.id)
            by_id_anon = {it["id"]: it for it in following_anon["items"]}
            assert by_id_anon[u2.id]["is_following"] is False
            assert by_id_anon[u3.id]["is_following"] is False
            assert by_id_anon[u2.id]["follower_count"] == 1
            assert by_id_anon[u3.id]["follower_count"] == 2
        finally:
            await _cleanup_users(db, u1.id, u2.id, u3.id, u4.id)
            await db.commit()
