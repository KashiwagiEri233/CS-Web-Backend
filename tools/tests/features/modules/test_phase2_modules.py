"""Phase 2 集成测试（需要可用 PostgreSQL）。

覆盖：
1. 公告：创建/生效过滤（过期/角色定向）/更新/删除；
2. 通知：创建/列表分页/已读管理/广播；
3. 入社申请：提交（游客+登录）/我的申请/审批 + 通知；
4. 管理员用户：禁用/启用/重置密码/保护规则（SELF_DISABLE/ROOT_PROTECTED/NO_CHANGE）；
5. 事件总线：user.registered → 欢迎通知。
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.exceptions import AuthorizationException, ConflictException
from app.core.timezone import now_utc
from app.database import get_session
from app.models.user import User
from app.schemas.announcement import AnnouncementInput
from app.schemas.join import JoinApplicationInput
from app.services.announcement_service import AnnouncementService
from app.services.auth.auth_service import AuthService
from app.services.join_service import JoinService
from app.services.notification_service import NotificationService
from app.services.user.user_service import UserService


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


async def _make_user(
    db, email: str, *, superuser: bool = False, role: str = "user"
) -> User:
    from app.models.role import Role

    user = User(
        username=f"u_{_sfx()}",
        email=email,
        hashed_password="$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyh",
        is_active=True,
        is_superuser=superuser,
    )
    db.add(user)
    await db.flush()
    if role != "user":
        r = (
            await db.execute(select(Role).where(Role.name == role))
        ).scalar_one_or_none()
        if r is None:
            r = Role(name=role, description=f"test role {role}")
            db.add(r)
            await db.flush()
        from app.models.user import user_roles
        from sqlalchemy import insert

        await db.execute(insert(user_roles).values(user_id=user.id, role_id=r.id))
    await db.commit()
    return user


async def _cleanup_users(db, *user_ids: int) -> None:
    from sqlalchemy import text

    for uid in user_ids:
        for table in (
            "refresh_tokens",
            "login_history",
            "password_history",
            "verification_codes",
            "notifications",
            "join_applications",
            "user_roles",
        ):
            try:
                async with db.begin_nested():
                    await db.execute(
                        text(f"DELETE FROM {table} WHERE user_id=:i"), {"i": uid}
                    )
            except Exception:
                pass
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()


@pytest.mark.integration
async def test_announcement_lifecycle(integration_db_ready):
    from datetime import timedelta

    from app.models.notification import Announcement

    sfx = _sfx()
    async with get_session() as db:
        svc = AnnouncementService(db)
        created = await svc.create(
            1,
            AnnouncementInput(
                title=f"公告-{sfx}",
                content="内容",
                priority=5,
                target_roles=["admin"],
            ),
        )
        try:
            # 生效列表：无角色看不到定向公告
            active = await svc.list_active(roles=None)
            assert all(a.id != created.id for a in active)
            active_admin = await svc.list_active(roles=["admin"])
            assert any(a.id == created.id for a in active_admin)

            # 过期公告不生效
            expired = await svc.create(
                1,
                AnnouncementInput(
                    title=f"过期-{sfx}",
                    content="x",
                    expires_at=now_utc() - timedelta(hours=1),
                ),
            )
            active_after = await svc.list_active()
            assert all(a.id != expired.id for a in active_after)

            # 更新 + 删除
            updated = await svc.update(
                created.id,
                AnnouncementInput(title=f"改名-{sfx}", content="新内容"),
            )
            assert updated.title == f"改名-{sfx}"
            await svc.delete(created.id)
            from app.core.exceptions import NotFoundException

            with pytest.raises(NotFoundException):
                await svc.get(created.id)
        finally:
            await db.execute(
                delete(Announcement).where(Announcement.title.like(f"%{sfx}%"))
            )
            await db.commit()


@pytest.mark.integration
async def test_notification_and_broadcast(integration_db_ready):
    async with get_session() as db:
        user = await _make_user(db, f"ntf_{_sfx()}@t.com")
        user2 = await _make_user(db, f"ntf2_{_sfx()}@t.com")
        svc = NotificationService(db)
        try:
            n1 = await svc.create(
                user_id=user.id, type="system", title="欢迎", content="hi"
            )
            n2 = await svc.create(
                user_id=user.id, type="admin", title="通知", content="x"
            )

            items, total = await svc.list_for_user(user.id, limit=10)
            assert total == 2
            assert items[0].id in (n1.id, n2.id)
            assert await svc.unread_count(user.id) == 2

            await svc.mark_read(user.id, n1.id)
            assert await svc.unread_count(user.id) == 1

            # 无权读他人通知
            from app.core.exceptions import NotFoundException

            with pytest.raises(NotFoundException):
                await svc.mark_read(user2.id, n1.id)

            n = await svc.mark_all_read(user.id)
            assert n == 1
            assert await svc.unread_count(user.id) == 0

            # 广播
            sent = await svc.broadcast(
                title="全站",
                content="通知",
                sender_id=user.id,
                user_ids=[user.id, user2.id],
            )
            assert sent == 2
            assert await svc.unread_count(user2.id) == 1

            await _cleanup_users(db, user.id, user2.id)
        except Exception:
            await _cleanup_users(db, user.id, user2.id)
            raise


@pytest.mark.integration
async def test_join_submit_and_review(integration_db_ready):
    async with get_session() as db:
        user = await _make_user(db, f"join_{_sfx()}@t.com")
        admin = await _make_user(db, f"admin_{_sfx()}@t.com", role="admin")
        svc = JoinService(db)
        try:
            # 游客提交
            guest_app = await svc.submit(
                JoinApplicationInput(
                    applicant_name="张三",
                    student_id="20260001",
                    major="计算机",
                    reason="想加入",
                ),
                user_id=None,
            )
            assert guest_app.user_id is None

            # 登录提交
            user_app = await svc.submit(
                JoinApplicationInput(
                    applicant_name="李四",
                    student_id="20260002",
                    major="软件工程",
                    tech_tags=["web"],
                    reason="学习",
                    contact_qq="12345",
                ),
                user_id=user.id,
            )
            assert user_app.user_id == user.id
            assert len(await svc.list_mine(user.id)) == 1

            # 审批 → 通知
            approved = await svc.review(
                user_app.id,
                status="approved",
                admin_id=admin.id,
                admin_username=admin.username,
                review_note="欢迎",
            )
            assert approved.status == "approved"
            ntf = NotificationService(db)
            _, total = await ntf.list_for_user(user.id, limit=10)
            assert total == 1

            # 重复审批
            with pytest.raises(ConflictException):
                await svc.review(
                    user_app.id,
                    status="rejected",
                    admin_id=admin.id,
                    admin_username=admin.username,
                )

            await _cleanup_users(db, user.id, admin.id)
        except Exception:
            await _cleanup_users(db, user.id, admin.id)
            raise


@pytest.mark.integration
async def test_admin_user_protections(integration_db_ready):
    async with get_session() as db:
        root = await _make_user(db, f"root_{_sfx()}@t.com", superuser=True)
        admin = await _make_user(db, f"adm_{_sfx()}@t.com", role="admin")
        normal = await _make_user(db, f"usr_{_sfx()}@t.com")
        svc = UserService(db)
        try:
            # 禁用普通用户（管理员）
            await svc.set_user_active_admin(admin, normal.id, active=False)
            assert (await svc.get_user(normal.id)).is_active is False

            # NO_CHANGE
            with pytest.raises(ConflictException):
                await svc.set_user_active_admin(admin, normal.id, active=False)

            # 超级管理员不可被禁用
            with pytest.raises(AuthorizationException):
                await svc.set_user_active_admin(admin, root.id, active=False)

            # SELF_DISABLE
            with pytest.raises(AuthorizationException):
                await svc.set_user_active_admin(admin, admin.id, active=False)

            # 自定义重置密码仅超管
            with pytest.raises(AuthorizationException):
                await svc.reset_password_admin(
                    admin, normal.id, default_password=False, new_password="NewPass123!"
                )

            # 默认密码重置（管理员可，目标普通用户）
            import app.core.config as cfg

            cfg.settings.PASSWORD_RESET_DEFAULT = "DefaultReset123!"
            await svc.set_user_active_admin(admin, normal.id, active=True)
            await svc.reset_password_admin(admin, normal.id, default_password=True)
            auth = AuthService(db)
            result = await auth.login_by_email(
                normal.email,
                "DefaultReset123!",
                {"ip_address": "1.1.1.1", "user_agent": "t"},
            )
            assert result["pair"] is not None

            # 硬删除（仅超管）
            await svc.delete_user_admin(root, normal.id)

            await _cleanup_users(db, root.id, admin.id)
        except Exception:
            await _cleanup_users(db, root.id, admin.id)
            raise


@pytest.mark.integration
async def test_user_registered_welcome_event(integration_db_ready):
    """事件总线：注册 → 欢迎通知（订阅者需已在 main 注册；此处手动注册兜底）。"""
    from app.services.notification_events import register_notification_events

    register_notification_events()

    email = f"evt_{_sfx()}@t.com"
    async with get_session() as db:
        auth = AuthService(db)
        user = None
        try:
            await auth.register(
                email, "Str0ng!Pass123", {"ip_address": "1.1.1.1", "user_agent": "t"}
            )
            user = await auth.user_repo.get_by_email(email)
            # 等待异步订阅者完成
            import asyncio

            await asyncio.sleep(0.2)
            ntf = NotificationService(db)
            _, total = await ntf.list_for_user(user.id, limit=10)
            assert total >= 1
            items, _ = await ntf.list_for_user(user.id, limit=10)
            assert items[0].title == "欢迎加入"
            await _cleanup_users(db, user.id)
        except Exception:
            if user:
                await _cleanup_users(db, user.id)
            raise
