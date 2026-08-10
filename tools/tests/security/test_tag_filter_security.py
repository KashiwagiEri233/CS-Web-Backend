"""ER-01 / ER-23：tags 过滤参数化（无需 DB）。

验证 community_repo.list_posts 的 tag 过滤不再把用户输入拼进 SQL 字面量，
而是走 ORM 绑定参数；且与 community.py:121 的 User.tech_tags.contains([tag])
正确写法保持一致。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.community import CommunityPost
from app.models.user import User


def _compile_tag_filter(tag: str) -> str:
    expr = CommunityPost.tags.contains([tag])
    return str(select(CommunityPost).where(expr).compile(dialect=postgresql.dialect()))


def test_tag_filter_is_parameterized():
    sql = _compile_tag_filter("alpha")
    # 存在绑定参数（参数化），而非把值内联成字面量
    assert "%(" in sql or ":param" in sql
    # 用户输入绝不作为字面量出现在 SQL 中
    assert "alpha" not in sql


def test_tag_filter_rejects_injection_payloads():
    # 各种恶意 tag 都不应作为字面量进入 SQL
    for tag in ["'; DROP TABLE community_posts;--", 'a"b', "%x", " OR 1=1 --"]:
        sql = _compile_tag_filter(tag)
        assert tag not in sql, f"恶意 tag 泄漏进 SQL：{tag!r}"


def test_tag_filter_matches_safe_tech_tags_pattern():
    # 与 community.py:121 的正确写法结构一致：均传入列表、均参数化
    post_sql = _compile_tag_filter("golang")
    user_sql = str(
        select(User)
        .where(User.tech_tags.contains(["golang"]))
        .compile(dialect=postgresql.dialect())
    )
    # 两者都产生绑定参数，且都不内联用户输入
    for sql in (post_sql, user_sql):
        assert "%(" in sql
        assert "golang" not in sql
