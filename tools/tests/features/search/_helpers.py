"""search 集成测试共用的通用用户构造/清理辅助函数。

从原 community 测试平移而来：这些 helper 仅做泛型用户创建与级联清理，
与 community 业务无耦合，故置于 search 包内使其自洽，避免跨业务域依赖。
"""

import uuid

from sqlalchemy import text

from app.models.user import User


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
                    text("DELETE FROM community_series WHERE created_by=:i"),
                    {"i": uid},
                )
        except Exception:
            pass
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
    await db.commit()
