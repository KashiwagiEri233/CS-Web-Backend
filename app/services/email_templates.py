from __future__ import annotations

from pathlib import Path
from string import Template

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"


def render_template(name: str, **ctx) -> str:
    """读取 `TEMPLATE_DIR/name` 并替换 `${var}` 占位符。"""
    path = TEMPLATE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"邮件模板不存在: {path}")
    raw = path.read_text(encoding="utf-8")
    try:
        return Template(raw).substitute(**ctx)
    except KeyError as exc:
        raise KeyError(f"邮件模板 {name} 缺少变量: {exc.args[0]}") from exc
