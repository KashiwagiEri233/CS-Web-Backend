"""依赖清单一致性：pyproject.toml 与 requirements.txt 必须描述同一套运行时依赖。

背景：项目同时维护两份运行时依赖清单——``pyproject.toml`` 的 ``[project].dependencies``
和 ``requirements.txt``（后者是 pip-compile 生成 requirements.lock 的输入）。两份清单
靠人工同步，加一个包只改一边不会有任何报错，直到运行时才 ImportError 或者装出不同版本。
这个测试把「静默漂移」变成「CI 直接失败」。

新增/升级依赖时请同时改两个文件，并重新生成 lock：
    pip-compile --generate-hashes --strip-extras -o requirements.lock requirements.txt
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


def _requirements_txt_dependencies() -> set[tuple[str, frozenset[str], str]]:
    parsed = set()
    for line in (
        (_PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    ):
        line = line.split("#", 1)[0].strip()
        # 跳过空行与 pip 选项行（-r / -c / --hash 等）
        if not line or line.startswith("-"):
            continue
        parsed.add(_parse_requirement(line))
    return parsed


def test_pyproject_and_requirements_txt_agree():
    from_pyproject = _pyproject_dependencies()
    from_requirements = _requirements_txt_dependencies()

    only_in_pyproject = from_pyproject - from_requirements
    only_in_requirements = from_requirements - from_pyproject

    assert not only_in_pyproject and not only_in_requirements, (
        "pyproject.toml 与 requirements.txt 的运行时依赖不一致（两处都要改）：\n"
        f"  仅在 pyproject.toml: {sorted(only_in_pyproject)}\n"
        f"  仅在 requirements.txt: {sorted(only_in_requirements)}"
    )


def test_every_declared_dependency_is_pinned_or_bounded():
    """每个依赖都必须带版本约束，否则 lock 重新生成时可能悄悄跳大版本。"""
    unbounded = [name for name, _extras, spec in _pyproject_dependencies() if not spec]
    assert not unbounded, f"以下依赖未声明任何版本约束: {sorted(unbounded)}"
