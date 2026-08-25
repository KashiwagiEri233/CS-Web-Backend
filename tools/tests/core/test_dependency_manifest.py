"""依赖清单一致性：pyproject.toml 与 uv.lock 必须描述同一套运行时依赖。

背景：依赖管理已收敛为 uv 单源（2026-08-17，C-7/A'）——``pyproject.toml`` 的
``[project].dependencies`` 是唯一事实源，``uv.lock`` 由 ``uv lock`` 生成；CI / Docker
消费的 ``requirements*.lock`` 是 ``uv export --hashed`` 的派生物。本测试把「锁文件与
声明漂移」变成「CI 直接失败」：

1. pyproject 声明的每个直接依赖都必须出现在 uv.lock 包集中（uv.lock 缺失 / 过期即失败）；
2. 每个直接依赖都必须带版本约束，否则 lock 重新生成时可能悄悄跳大版本。

新增 / 升级依赖时：改 ``pyproject.toml`` → ``uv lock`` → ``uv export --hashed``
重新生成 ``requirements.lock`` / ``requirements-dev.lock``。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

# 测试现已位于 tools/tests/core/，需向上四级到达仓库根。
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# name[extras]specifier —— 覆盖 requirements 与 PEP 508 里本项目实际用到的写法
_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[(?P<extras>[^\]]*)\])?"
    r"(?P<spec>.*)$"
)


def _canonical_name(name: str) -> str:
    """PEP 503 名称规范化：PyJWT / email_validator -> pyjwt / email-validator。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirement(raw: str) -> tuple[str, frozenset[str], str]:
    """把一行依赖声明解析成 (规范化名, extras 集合, 去空白的版本约束)。"""
    match = _REQUIREMENT_RE.match(raw.strip())
    assert match is not None, f"无法解析依赖声明: {raw!r}"
    extras = match.group("extras") or ""
    return (
        _canonical_name(match.group("name")),
        frozenset(_canonical_name(e) for e in extras.split(",") if e.strip()),
        match.group("spec").replace(" ", ""),
    )


def _pyproject_dependencies() -> set[tuple[str, frozenset[str], str]]:
    data = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {_parse_requirement(item) for item in data["project"]["dependencies"]}


def _uv_lock_package_names() -> set[str]:
    """uv.lock（TOML）中所有 [[package]] 的规范化名集合（含直接与传递依赖）。"""
    data = tomllib.loads((_PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {_canonical_name(pkg["name"]) for pkg in data.get("package", [])}


def test_pyproject_deps_are_locked_in_uv_lock():
    """pyproject 声明的每个直接依赖都必须已进入 uv.lock（锁缺失 / 过期即失败）。"""
    from_pyproject = {name for name, _extras, _spec in _pyproject_dependencies()}
    locked = _uv_lock_package_names()
    missing = sorted(from_pyproject - locked)
    assert not missing, (
        "以下 pyproject.toml 直接依赖未出现在 uv.lock 中（须 `uv lock` 重新生成）：\n"
        f"  {missing}"
    )


def test_every_declared_dependency_is_pinned_or_bounded():
    """每个依赖都必须带版本约束，否则 lock 重新生成时可能悄悄跳大版本。"""
    unbounded = [name for name, _extras, spec in _pyproject_dependencies() if not spec]
    assert not unbounded, f"以下依赖未声明任何版本约束: {sorted(unbounded)}"
