import pytest

from app.services import email_templates
from app.services.email_templates import render_template


def test_render_template_substitutes_all_placeholders():
    html = render_template(
        "verification_code.html",
        code="123456",
        ttl_minutes=10,
        year=2026,
    )

    assert "123456" in html
    assert "10" in html
    assert "${" not in html


def test_render_template_raises_when_template_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(email_templates, "TEMPLATE_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="邮件模板不存在"):
        render_template("missing.html")


def test_render_template_reports_missing_variable():
    with pytest.raises(KeyError, match="缺少变量"):
        render_template("verification_code.html", ttl_minutes=10, year=2026)
