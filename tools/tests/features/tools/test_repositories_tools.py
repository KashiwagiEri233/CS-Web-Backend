"""工具集仓储（tools_repo）真实 PostgreSQL 集成测试。

覆盖 ER-02 点名的零测试逻辑（仓储层直测，区别于 HTTP/phase 测试）：
- ResourceRepository：CRUD / status·resource_type·submitted_by 过滤 / 分页 / increment_view；
- TaskRepository：CRUD / status·category 过滤 / 认领（create/get/count_active/list_claims_*）；
- ComponentRegistryRepository：item / variant（replace_variants·toggle_variant）/ guide
  （upsert）。

注意：
- Resource.tech_tags 过滤（tools_repo.py:235）与 Exam.tech_tags（tools_repo.py:40）仍是
  与 community/events 同源的 JSONB-LIKE 退化 bug，本测试刻意不传 tag 参数，避免命中；
  是否并入 tag 修复 MP 待用户拍板。
- tools 域表均无 DB 级 CASCADE：Resource.submitted_by / Task.created_by /
  TaskClaim.task_id 与 user_id / Variant.item_id 均为 NO ACTION，
  清理顺序须 子表 → 父表 → users。

本地无法连接数据库时自动 skip；CI 严格模式下直接失败。
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.timezone import now_utc
from app.database import get_session
from app.models.component_registry import (
    ComponentRegistryGuide,
    ComponentRegistryItem,
    ComponentRegistryVariant,
)
from app.models.exam import Exam
from app.models.resource import Resource
from app.models.task import Task, TaskClaim, TaskClaimMember
from app.models.user import User
from app.repositories.tools_repo import (
    ComponentRegistryRepository,
    ExamRepository,
    ResourceRepository,
)
from app.repositories.task_repo import TaskRepository

pytestmark = pytest.mark.integration


async def _make_user(db, sfx: str) -> int:
    user = User(
        username=f"itest_tools_u_{sfx}",
        email=f"itest_tools_{sfx}@t.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user.id


async def _cleanup(
    db, uids=None, resource_ids=None, task_ids=None, item_ids=None, exam_ids=None
) -> None:
    """按依赖顺序清场：resources / exams / claims→tasks /
    variants→guides→items → users。"""
    if resource_ids:
        await db.execute(delete(Resource).where(Resource.id.in_(resource_ids)))
    if exam_ids:
        await db.execute(delete(Exam).where(Exam.id.in_(exam_ids)))
    if task_ids:
        claim_ids = select(TaskClaim.id).where(TaskClaim.task_id.in_(task_ids))
        await db.execute(
            delete(TaskClaimMember).where(TaskClaimMember.claim_id.in_(claim_ids))
        )
        await db.execute(delete(TaskClaim).where(TaskClaim.task_id.in_(task_ids)))
        await db.execute(delete(Task).where(Task.id.in_(task_ids)))
    if item_ids:
        await db.execute(
            delete(ComponentRegistryVariant).where(
                ComponentRegistryVariant.item_id.in_(item_ids)
            )
        )
        await db.execute(
            delete(ComponentRegistryGuide).where(
                ComponentRegistryGuide.item_id.in_(item_ids)
            )
        )
        await db.execute(
            delete(ComponentRegistryItem).where(ComponentRegistryItem.id.in_(item_ids))
        )
    if uids:
        await db.execute(delete(User).where(User.id.in_(uids)))
    await db.commit()


# ---------------------------------------------------------------------------
# 1) ResourceRepository：CRUD + 过滤 + 分页 + increment_view
#    （刻意不传 tag：tools_repo.py:235 存在 JSONB-LIKE 退化 bug，待决策）
# ---------------------------------------------------------------------------
async def test_resource_crud_filters_view(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        submitter = await _make_user(db, f"{sfx}sub")
        reviewer = await _make_user(db, f"{sfx}rev")
    resource_ids: list[int] = []
    try:
        async with get_session() as db:
            repo = ResourceRepository(db)
            specs = [
                ("article", "approved"),
                ("article", "approved"),
                ("video", "pending"),
            ]
            for i, (typ, status) in enumerate(specs):
                r = await repo.create(
                    {
                        "title": f"res-{sfx}-{i}",
                        "url": f"https://t.com/{sfx}/{i}",
                        "resource_type": typ,
                        "status": status,
                        "submitted_by": submitter,
                    }
                )
                resource_ids.append(r.id)
            await db.commit()
            r0_id, r1_id, _ = resource_ids

            # 过滤 + 分页（status/type 为全局过滤，用成员断言避免遗留行干扰 total）
            appr, appr_total = await repo.list_resources(
                status="approved", skip=0, limit=10
            )
            assert appr_total >= 2
            my_appr = [r for r in appr if r.title.startswith(f"res-{sfx}")]
            assert len(my_appr) == 2
            vid, vid_total = await repo.list_resources(
                resource_type="video", skip=0, limit=10
            )
            assert vid_total >= 1
            assert any(r.id == resource_ids[2] for r in vid)
            # submitted_by 为作用域过滤，total 确定性成立
            mine, mine_total = await repo.list_resources(
                submitted_by=submitter, skip=0, limit=2
            )
            assert mine_total == 3 and len(mine) == 2

            # get_by_id / update
            assert (await repo.get_by_id(r0_id)).title == f"res-{sfx}-0"
            r0 = await repo.get_by_id(r0_id)
            await repo.update(r0, {"status": "rejected", "review_note": "nope"})
            await db.commit()
            assert (await repo.get_by_id(r0_id)).status == "rejected"

            # increment_view
            await repo.increment_view(r0_id)
            await db.commit()
            assert (await repo.get_by_id(r0_id)).view_count == 1

            # delete（含不存在返回 False）
            assert await repo.delete(r1_id) is True
            await db.commit()
            assert (await repo.get_by_id(r1_id)) is None
            assert await repo.delete(999999) is False
    finally:
        async with get_session() as db:
            await _cleanup(db, [submitter, reviewer], resource_ids=resource_ids)


# ---------------------------------------------------------------------------
# 1.5) tag 过滤回归 —— Resource.tech_tags 走 JSONB @> 包含
# ---------------------------------------------------------------------------
async def test_resource_tag_filter_jsonb_containment(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        submitter = await _make_user(db, f"{sfx}sub")
    resource_ids: list[int] = []
    try:
        async with get_session() as db:
            repo = ResourceRepository(db)
            for i in range(5):
                tag = "python" if i % 2 == 0 else "golang"
                r = await repo.create(
                    {
                        "title": f"rtag-{sfx}-{i}",
                        "url": f"https://t.com/{sfx}/{i}",
                        "resource_type": "article",
                        "status": "approved",
                        "submitted_by": submitter,
                        "tech_tags": [tag],
                    }
                )
                resource_ids.append(r.id)
            await db.commit()

            # 参数化 JSONB 包含：python 命中 3 条，golang 命中 2 条
            py, py_total = await repo.list_resources(tag="python", skip=0, limit=10)
            assert py_total >= 3
            assert len([r for r in py if r.title.startswith(f"rtag-{sfx}")]) == 3
            go, go_total = await repo.list_resources(tag="golang", skip=0, limit=10)
            assert go_total >= 2
            assert len([r for r in go if r.title.startswith(f"rtag-{sfx}")]) == 2

            # 注入型 tag 不应报错也不应匹配
            inj, inj_total = await repo.list_resources(
                tag="python' OR '1'='1", skip=0, limit=10
            )
            assert not any(r.title.startswith(f"rtag-{sfx}") for r in inj)
    finally:
        async with get_session() as db:
            await _cleanup(db, [submitter], resource_ids=resource_ids)


# ---------------------------------------------------------------------------
# 2) TaskRepository（P3 新模型）：CRUD + 过滤 + 执行实例/成员快照
# ---------------------------------------------------------------------------
async def test_task_crud_and_claims(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        creator = await _make_user(db, f"{sfx}cr")
        u1 = await _make_user(db, f"{sfx}u1")
        u2 = await _make_user(db, f"{sfx}u2")
    task_ids: list[int] = []
    try:
        async with get_session() as db:
            repo = TaskRepository(db)
            t1 = await repo.create(
                {
                    "title": f"task-{sfx}-1",
                    "description": "d",
                    "category": "dev",
                    "status": "published",
                    "publisher_id": creator,
                    "execution_mode": "single",
                    "reward_total": 10,
                    "max_members": 1,
                    "deadline": now_utc(),
                    "visibility": "public",
                }
            )
            t2 = await repo.create(
                {
                    "title": f"task-{sfx}-2",
                    "description": "d",
                    "category": "design",
                    "status": "draft",
                    "publisher_id": creator,
                    "execution_mode": "single",
                    "reward_total": 5,
                    "max_members": 1,
                    "deadline": now_utc(),
                    "visibility": "public",
                }
            )
            await db.commit()
            task_ids += [t1.id, t2.id]
            t1_id, t2_id = t1.id, t2.id

            assert (await repo.get(t1_id)).title == f"task-{sfx}-1"
            pub = await repo.list_tasks(
                conditions=[Task.status == "published", Task.title.like(f"%{sfx}%")]
            )
            assert any(t.id == t1_id for t in pub)
            dev = await repo.list_tasks(
                conditions=[Task.category == "dev", Task.title.like(f"%{sfx}%")]
            )
            assert any(t.id == t1_id for t in dev)

            claim = await repo.create_claim(
                {"task_id": t1_id, "leader_user_id": u1, "status": "active"}
            )
            await repo.add_claim_member(claim.id, u1, True)
            await db.commit()
            claim_id = claim.id
            assert (await repo.get_open_claim(t1_id)) is not None
            assert len(await repo.list_claim_members(claim_id)) == 1
            assert await repo.count_claims_for_user(u1) == 1
            assert await repo.user_has_active_claim(u1) is True

            assert len(await repo.list_claims_for_task(t1_id)) == 1
            assert len(await repo.list_claims_for_user(u1)) == 1

            t1_obj = await repo.get(t1_id)
            await repo.update(t1_obj, {"status": "closed", "closed_at": now_utc()})
            await db.commit()
            assert (await repo.get(t1_id)).status == "closed"
            # 恢复 published 以便清理不残留开放执行实例约束
            await repo.update(t1_obj, {"status": "published"})
            await db.commit()
    finally:
        async with get_session() as db:
            await _cleanup(db, [creator, u1, u2], task_ids=task_ids)


# ---------------------------------------------------------------------------
# 3) ComponentRegistryRepository：item / variant / guide
# ---------------------------------------------------------------------------
async def test_component_registry_items_variants_guide(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    item_ids: list[int] = []
    try:
        async with get_session() as db:
            repo = ComponentRegistryRepository(db)
            item = await repo.create_item(
                {
                    "name": f"btn-{sfx}",
                    "slug": f"btn-{sfx}",
                    "category": "general",
                    "migration_status": "legacy",
                }
            )
            item_id = item.id
            item_ids.append(item_id)
            await db.commit()

            # get_item / get_item_by_slug / list_items
            assert (await repo.get_item(item_id)).name == f"btn-{sfx}"
            assert (await repo.get_item_by_slug(f"btn-{sfx}")) is not None
            assert (await repo.get_item_by_slug("nope-does-not-exist")) is None
            all_items = await repo.list_items()
            assert any(i.id == item_id for i in all_items)

            # replace_variants：先放两条
            await repo.replace_variants(
                item_id,
                [
                    {
                        "size": "md",
                        "color": "primary",
                        "state": "default",
                        "is_enabled": True,
                    },
                    {
                        "size": "lg",
                        "color": "primary",
                        "state": "default",
                        "is_enabled": True,
                    },
                ],
            )
            await db.commit()
            variants = await repo.list_variants(item_id)
            assert len(variants) == 2

            # 同 (size,color,state) 再放一条走 upsert 路径，不新增
            await repo.replace_variants(
                item_id,
                [
                    {
                        "size": "md",
                        "color": "primary",
                        "state": "default",
                        "is_enabled": False,
                    }
                ],
            )
            await db.commit()
            variants2 = await repo.list_variants(item_id)
            assert len(variants2) == 2
            md_variant = next(v for v in variants2 if v.size == "md")
            assert md_variant.is_enabled is False

            # toggle_variant
            assert await repo.toggle_variant(md_variant.id, True) is True
            await db.commit()
            assert (await repo.get_variant(item_id, md_variant.id)).is_enabled is True
            assert await repo.toggle_variant(999999, True) is False

            # guide：upsert 首次 + 覆盖
            await repo.upsert_guide(item_id, ["use-a"], ["anti-b"])
            await db.commit()
            assert (await repo.get_guide(item_id)) is not None
            await repo.upsert_guide(item_id, ["use-a2"], ["anti-b2"])
            await db.commit()
            g2 = await repo.get_guide(item_id)
            assert g2.use_cases == ["use-a2"] and g2.anti_patterns == ["anti-b2"]

            # delete_item：无子行时成功（变体 FK 为 NO ACTION，有变体时由 DB 拒绝）
            item2 = await repo.create_item(
                {
                    "name": f"btn2-{sfx}",
                    "slug": f"btn2-{sfx}",
                    "category": "general",
                    "migration_status": "legacy",
                }
            )
            item2_id = item2.id
            item_ids.append(item2_id)
            await db.commit()
            assert await repo.delete_item(item2_id) is True
            await db.commit()
            assert await repo.get_item(item2_id) is None
            assert await repo.delete_item(999999) is False
    finally:
        async with get_session() as db:
            await _cleanup(db, item_ids=item_ids)


# ---------------------------------------------------------------------------
# 5) 事务回滚 —— 未提交插入回滚后消失
# ---------------------------------------------------------------------------
async def test_tools_transaction_rollback(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        uid = await _make_user(db, sfx)
    try:
        async with get_session() as db2:
            repo = ResourceRepository(db2)
            r = await repo.create(
                {
                    "title": f"rb-{sfx}",
                    "url": f"https://t.com/{sfx}",
                    "submitted_by": uid,
                }
            )
            rid = r.id
            await db2.rollback()
        async with get_session() as db3:
            assert await ResourceRepository(db3).get_by_id(rid) is None
    finally:
        async with get_session() as db:
            await _cleanup(db, [uid])


# ---------------------------------------------------------------------------
# 6) Exam 冒烟 —— list_exams 的 tag 过滤走 JSONB @> 包含（无专属测试套件，
#    仅验证修复不报错、命中正确）
# ---------------------------------------------------------------------------
async def test_exam_tag_filter_smoke(integration_db_ready):
    sfx = uuid.uuid4().hex[:8]
    async with get_session() as db:
        creator = await _make_user(db, f"{sfx}ex")
    exam_ids: list[int] = []
    try:
        async with get_session() as db:
            repo = ExamRepository(db)
            exam = await repo.create(
                {
                    "title": f"exam-{sfx}",
                    "status": "published",
                    "created_by": creator,
                    "tech_tags": ["python"],
                }
            )
            exam_ids.append(exam.id)
            await db.commit()

            hit, hit_total = await repo.list_exams(tag="python", skip=0, limit=10)
            assert hit_total >= 1 and any(e.id == exam.id for e in hit)
            miss, miss_total = await repo.list_exams(tag="golang", skip=0, limit=10)
            assert not any(e.id == exam.id for e in miss)
            # 注入型 tag 不应报错也不应匹配
            inj, inj_total = await repo.list_exams(
                tag="python' OR '1'='1", skip=0, limit=10
            )
            assert not any(e.id == exam.id for e in inj)
    finally:
        async with get_session() as db:
            await _cleanup(db, [creator], exam_ids=exam_ids)
