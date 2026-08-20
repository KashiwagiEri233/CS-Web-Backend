"""工具集路由 HTTP → 鉴权 → Service → Repository → PostgreSQL 完整链路。

补 ER-11 盲区：tools 路由此前无真实 DB 的 HTTP 级测试
（test_phase5_tools 与 repo 层测试均不覆盖路由/鉴权接线）。覆盖：
- 资源：公开列表（status=approved）/ tag 过滤（tools_repo.py:235 修复的 HTTP 回归）/ 详情 / 用户提交；
- 任务：公开列表 / 详情 / 认领 / 我的认领 / 提交完成；
- 考试：公开列表 tag 过滤（tools_repo.py:40 修复的 HTTP 回归）/ 详情 / 题目列表；
- 积分：我的积分 / 排行榜；
- 组件注册表：创建 / 列表 / 详情 / 变体替换 / 指南更新。

管理端（RBAC 权限）与答题提交不在本测试范围。本地无法连接数据库时自动
skip；CI 严格模式下直接失败。
"""

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.security import async_get_password_hash
from app.database import get_session
from app.main import create_app
from app.models.component_registry import ComponentRegistryItem
from app.models.exam import Exam
from app.models.resource import Resource
from app.models.task import Task
from app.models.user import User

pytestmark = pytest.mark.integration

_PASSWORD = "StrongPass1!"


async def _make_user(db, sfx: str) -> int:
    user = User(
        username=f"itest_http_tools_{sfx}",
        email=f"itest_http_tools_{sfx}@t.com",
        hashed_password=await async_get_password_hash(_PASSWORD),
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user.id


async def _cleanup(
    db,
    user_ids: list[int],
    resource_ids=None,
    task_ids=None,
    exam_ids=None,
    item_ids=None,
) -> None:
    """按依赖顺序清场：claims→resources/exams/tasks→registry 子表→items→鉴权表→users。"""
    if task_ids:
        try:
            async with db.begin_nested():
                await db.execute(
                    text("DELETE FROM task_claims WHERE task_id = ANY(:ids)"),
                    {"ids": task_ids},
                )
        except Exception:
            pass
    if item_ids:
        for table in ("component_registry_variants", "component_registry_guides"):
            try:
                async with db.begin_nested():
                    await db.execute(
                        text(f"DELETE FROM {table} WHERE item_id = ANY(:ids)"),
                        {"ids": item_ids},
                    )
            except Exception:
                pass
    if resource_ids:
        await db.execute(
            text("DELETE FROM resources WHERE id = ANY(:ids)"), {"ids": resource_ids}
        )
    if exam_ids:
        await db.execute(
            text("DELETE FROM exams WHERE id = ANY(:ids)"), {"ids": exam_ids}
        )
    if task_ids:
        await db.execute(
            text("DELETE FROM tasks WHERE id = ANY(:ids)"), {"ids": task_ids}
        )
    if item_ids:
        await db.execute(
            text("DELETE FROM component_registry_items WHERE id = ANY(:ids)"),
            {"ids": item_ids},
        )
    for table in (
        "refresh_tokens",
        "login_history",
        "password_history",
        "notifications",
        "two_factor_auth",
        "verification_codes",
        "password_reset_requests",
        "user_roles",
    ):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                    {"ids": user_ids},
                )
        except Exception:
            pass
    await db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})
    await db.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login-json",
        json={"username": username, "password": _PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


async def test_tools_http_user_flow(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        creator_id = await _make_user(db, f"{sfx}cr")
        user_id = await _make_user(db, f"{sfx}us")

        resource = Resource(
            title=f"http-资源-{sfx}",
            url=f"https://t.com/{sfx}",
            resource_type="article",
            tech_tags=["python"],
            status="approved",
            submitted_by=creator_id,
        )
        db.add(resource)

        task = Task(
            title=f"http-任务-{sfx}",
            description="d",
            category="dev",
            status="published",
            max_claimants=1,
            created_by=creator_id,
        )
        db.add(task)

        exam = Exam(
            title=f"http-考试-{sfx}",
            description="d",
            status="published",
            tech_tags=["python"],
            created_by=creator_id,
        )
        db.add(exam)
        await db.commit()
        resource_id, task_id, exam_id = resource.id, task.id, exam.id

    new_resource_id: int | None = None
    item_id: int | None = None

    application = create_app()
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            h = await _login(client, f"itest_http_tools_{sfx}us")

            # ---- 资源：公开列表 + tag 过滤（tools_repo.py:235 修复的 HTTP 回归）
            res_lst = await client.get(
                "/api/v1/tools/resource", params={"tag": "python"}
            )
            assert res_lst.status_code == 200, res_lst.text
            assert any(r["id"] == resource_id for r in res_lst.json()["items"])

            # 详情（公开）
            res_det = await client.get(f"/api/v1/tools/resource/{resource_id}")
            assert res_det.status_code == 200, res_det.text
            assert res_det.json()["title"] == f"http-资源-{sfx}"

            # 用户提交资源（auth）
            created_res = await client.post(
                "/api/v1/tools/resource",
                headers=h,
                json={
                    "title": f"http-新资源-{sfx}",
                    "url": f"https://t.com/{sfx}/new",
                    "resource_type": "article",
                    "tech_tags": ["golang"],
                },
            )
            assert created_res.status_code == 201, created_res.text
            new_resource_id = created_res.json()["id"]

            # ---- 任务：列表 / 详情 / 认领 / 我的认领 / 提交
            task_lst = await client.get("/api/v1/tools/task")
            assert task_lst.status_code == 200, task_lst.text
            assert any(t["id"] == task_id for t in task_lst.json()["items"])
            task_det = await client.get(f"/api/v1/tools/task/{task_id}")
            assert task_det.status_code == 200, task_det.text

            claim = await client.post(
                f"/api/v1/tools/task/{task_id}/claim",
                headers=h,
                json={"note": "我来认领"},
            )
            assert claim.status_code == 201, claim.text
            claim_id = claim.json()["id"]
            assert claim.json()["status"] == "claimed"

            mine = await client.get("/api/v1/tools/task/claims/mine", headers=h)
            assert mine.status_code == 200, mine.text
            assert any(c["id"] == claim_id for c in mine.json()["claims"])

            submitted = await client.post(
                f"/api/v1/tools/task/claims/{claim_id}/submit", headers=h
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["status"] == "submitted"

            # ---- 考试：列表 tag 过滤（tools_repo.py:40 修复的 HTTP 回归）+ 详情 + 题目
            exam_lst = await client.get("/api/v1/tools/exam", params={"tag": "python"})
            assert exam_lst.status_code == 200, exam_lst.text
            assert any(e["id"] == exam_id for e in exam_lst.json()["items"])
            exam_det = await client.get(f"/api/v1/tools/exam/{exam_id}")
            assert exam_det.status_code == 200, exam_det.text
            questions = await client.get(f"/api/v1/tools/exam/{exam_id}/questions")
            assert questions.status_code == 200, questions.text
            assert questions.json()["questions"] == []

            # ---- 积分：我的积分 / 排行榜
            points = await client.get("/api/v1/tools/points", headers=h)
            assert points.status_code == 200, points.text
            lb = await client.get("/api/v1/tools/points/leaderboard")
            assert lb.status_code == 200, lb.text

            # ---- 组件注册表：创建 / 列表 / 详情 / 变体 / 指南
            comp = await client.post(
                "/api/v1/tools/component-registry",
                headers=h,
                json={"name": f"http-btn-{sfx}", "slug": f"http-btn-{sfx}"},
            )
            assert comp.status_code == 201, comp.text
            item_id = comp.json()["id"]

            comp_lst = await client.get("/api/v1/tools/component-registry")
            assert comp_lst.status_code == 200, comp_lst.text
            assert any(c["id"] == item_id for c in comp_lst.json()["components"])
            comp_det = await client.get(f"/api/v1/tools/component-registry/{item_id}")
            assert comp_det.status_code == 200, comp_det.text

            variants = await client.put(
                f"/api/v1/tools/component-registry/{item_id}/variants",
                headers=h,
                json=[{"size": "md", "color": "primary", "state": "default"}],
            )
            assert variants.status_code == 200, variants.text

            guide = await client.put(
                f"/api/v1/tools/component-registry/{item_id}/guide",
                headers=h,
                json={"use_cases": ["a"], "anti_patterns": ["b"]},
            )
            assert guide.status_code == 200, guide.text
    finally:
        async with get_session() as db:
            await _cleanup(
                db,
                [creator_id, user_id],
                resource_ids=(
                    [resource_id, new_resource_id] if new_resource_id else [resource_id]
                ),
                task_ids=[task_id],
                exam_ids=[exam_id],
                item_ids=[item_id] if item_id else None,
            )
