"""社区 v2 路由 HTTP → 鉴权 → Service → Repository → PostgreSQL 完整链路。

补 ER-11 盲区：community 路由此前无真实 DB 的 HTTP 级测试
（test_phase4_community 走 service 层、test_repositories_community 走 repo 层，
均不覆盖路由/鉴权接线）。本文件覆盖：
- 发帖（topic，需分类）/ 详情（匿名浏览）/ 列表 tag 过滤（community_repo JSONB @> 回归）；
- 评论 / 点赞 / 关注 + 关注列表 / 举报；
- 成员列表 tag 过滤（community.py:121 修复回归）/ 标签云 / 分类列表。

本地无法连接数据库时自动 skip；CI 严格模式下直接失败。
"""

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.security import async_get_password_hash
from app.database import get_session
from app.main import create_app
from app.models.community import CommunityCategory
from app.models.user import User

pytestmark = pytest.mark.integration

_PASSWORD = "StrongPass1!"


async def _make_user(db, sfx: str, *, tech_tags=None) -> int:
    user = User(
        username=f"itest_http_comm_{sfx}",
        email=f"itest_http_comm_{sfx}@t.com",
        hashed_password=await async_get_password_hash(_PASSWORD),
        is_active=True,
        is_superuser=False,
        tech_tags=tech_tags or [],
    )
    db.add(user)
    await db.commit()
    return user.id


async def _cleanup(db, user_ids: list[int], category_ids: list[int] | None = None) -> None:
    """先删鉴权/社区侧挂靠行（按 user_id），再删用户（社区 posts/comments 等
    author_id FK ondelete=CASCADE 随用户删除级联），最后删分类（created_by 为
    SET NULL 不随用户删除，且 posts 已级联删除后才可删）。"""
    for table in (
        "community_mentions",
        "community_post_views",
        "community_reactions",
        "community_favorites",
        "community_follows",
        "notifications",
        "user_roles",
        "refresh_tokens",
        "login_history",
        "password_history",
        "two_factor_auth",
        "verification_codes",
        "password_reset_requests",
    ):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                    {"ids": user_ids},
                )
        except Exception:
            pass
    for table, col in (("community_reports", "reporter_id"), ("community_series", "created_by")):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE {col} = ANY(:ids)"),
                    {"ids": user_ids},
                )
        except Exception:
            pass
    await db.execute(
        text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids}
    )
    if category_ids:
        await db.execute(
            text("DELETE FROM community_categories WHERE id = ANY(:ids)"),
            {"ids": category_ids},
        )
    await db.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login-json",
        json={"username": username, "password": _PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


async def test_community_http_user_flow(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        author_id = await _make_user(db, f"{sfx}a", tech_tags=["python"])
        interactor_id = await _make_user(db, f"{sfx}b")
        category = CommunityCategory(
            slug=f"itest-http-cat-{sfx}",
            name=f"cat-{sfx}",
            description="i",
            created_by=author_id,
        )
        db.add(category)
        await db.commit()
        category_id = category.id

    application = create_app()
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            h_author = await _login(client, f"itest_http_comm_{sfx}a")
            h_other = await _login(client, f"itest_http_comm_{sfx}b")

            # 发帖（topic 必须带 categoryId）
            r = await client.post(
                "/api/v1/community/posts",
                headers=h_author,
                json={
                    "kind": "topic",
                    "title": f"http-帖子-{sfx}",
                    "contentMarkdown": "正文",
                    "status": "published",
                    "categoryId": category_id,
                    "tags": ["python"],
                },
            )
            assert r.status_code == 201, r.text
            post_id = r.json()["id"]

            # 匿名浏览详情（触发浏览计数路径）
            d = await client.get(f"/api/v1/community/posts/{post_id}")
            assert d.status_code == 200, d.text
            assert d.json()["title"] == f"http-帖子-{sfx}"

            # 列表 tag 过滤（community_repo JSONB @> 修复的 HTTP 回归）
            lst = await client.get("/api/v1/community/posts", params={"tag": "python"})
            assert lst.status_code == 200, lst.text
            assert any(p["id"] == post_id for p in lst.json()["items"])

            # 标签云 / 分类（公开只读）
            tags = await client.get("/api/v1/community/tags")
            assert tags.status_code == 200, tags.text
            assert "python" in tags.json()["tags"]
            cats = await client.get("/api/v1/community/categories")
            assert cats.status_code == 200, cats.text
            assert any(c["id"] == category_id for c in cats.json())

            # 评论
            c = await client.post(
                f"/api/v1/community/posts/{post_id}/comments",
                headers=h_other,
                json={"contentMarkdown": "写得好"},
            )
            assert c.status_code == 201, c.text

            # 点赞（toggle on）
            like = await client.post(
                "/api/v1/community/reactions",
                headers=h_other,
                json={"targetType": "post", "targetId": post_id},
            )
            assert like.status_code == 200, like.text

            # 关注作者 → 关注列表含作者
            fw = await client.post(
                "/api/v1/community/follows",
                headers=h_other,
                json={"followingId": author_id},
            )
            assert fw.status_code == 200, fw.text
            fl = await client.get(
                "/api/v1/community/follows",
                headers=h_other,
                params={"type": "following"},
            )
            assert fl.status_code == 200, fl.text
            assert any(u["id"] == author_id for u in fl.json()["items"])

            # 举报
            rp = await client.post(
                "/api/v1/community/reports",
                headers=h_other,
                json={"targetType": "post", "targetId": post_id, "reason": "spam"},
            )
            assert rp.status_code == 201, rp.text

            # 成员列表 tag 过滤（community.py:121 修复回归：HTTP 不再 500 且命中）
            members = await client.get(
                "/api/v1/community/members",
                params={"tag": "python", "sort": "newest", "limit": 100},
            )
            assert members.status_code == 200, members.text
            assert any(m["id"] == author_id for m in members.json())
    finally:
        async with get_session() as db:
            await _cleanup(db, [author_id, interactor_id], [category_id])
