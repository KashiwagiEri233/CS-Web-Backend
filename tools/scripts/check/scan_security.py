#!/usr/bin/env python3
"""轻量安全静态扫描（G1 发布门禁补充）。

检查后端源码中两类高风险模式，发现即非零退出，用于 CI 阻断：

1. 全局 Origin 守卫缺失
   敏感端点（登录、注册、改密、OTP 校验等）需防 Login CSRF / 跨站请求。
   Origin 校验属于基础设施层关注点，应在全局中间件/依赖中实现一次。
   本检查确认整个代码库**存在** Origin 校验实现（出现任一守卫特征即视为已部署），
   若完全缺失则报警。

2. 疑似硬编码密钥
   匹配「密钥类变量名 = 非空字面量字符串」的赋值，排除 env 读取、空串、占位、
   已知安全常量（错误码、dummy 哈希、IP 哈希盐等白名单）。

用法：
    python tools/scripts/check/scan_security.py [--root app]
退出码：0 通过，1 发现风险，2 用法/IO 错误。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Origin 守卫的显式实现特征（整个代码库出现任一即视为已部署全局守卫）
ORIGIN_GUARD_HINTS = (
    "verify_origin",
    "check_origin",
    "validate_origin",
    "ALLOWED_ORIGINS",
    "allowed_origins",
    "origin_guard",
    'request.headers.get("origin"',
    "request.headers.get('origin'",
)

# 密钥类变量名（左侧匹配）
SECRET_VAR_NAMES = (
    "SECRET_KEY",
    "SECRET",
    "PASSWORD",
    "TOTP_ENCRYPTION_KEY",
    "AUTH_SESSION_SECRET",
    "API_KEY",
    "PRIVATE_KEY",
    "ENCRYPTION_KEY",
    "DATABASE_PASSWORD",
    "DATABASE_URL",
    "REDIS_URL",
)

# 硬编码密钥白名单：变量名 -> 允许的右侧字面量（安全常量，非真实密钥）
# 例：错误码常量、dummy 哈希、IP 哈希盐、占位符。
SAFE_LITERAL_WHITELIST = {
    "INVALID_CURRENT_PASSWORD",
    "PASSWORD_IN_HISTORY",
    "PASSWORD_RESET_NOT_CONFIGURED",
    "PASSWORD_RESET_EXPIRED",
    "PASSWORD_RESET_INVALID",
    "PASSWORD_RESET_RATE_LIMITED",
    # auth_service 的 dummy 哈希（防时序侧信道，非真实密码）
    "$2b$12$4wW.7xG3E9HU7z3dlkl37u4CVbHfGfgjXVLYP2A0WcBAe3ZQojbPS",
    # community_service 的 IP 哈希盐（非密钥，仅用于匿名化）
    "community-ip-hash",
    "change_me",
    "changeme",
    "placeholder",
    "CHANGE_ME",
}

# 文件/目录跳过
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "build", "alembic"}
SKIP_FILES = {"scan_security.py", "export_openapi.py", "init_database.py"}

PY_EXT = ".py"

# 匹配「变量名 = "字面量" 或 '字面量'」（捕获变量名与字面量）
ASSIGN_RE = re.compile(r"""^\s*([A-Z_][A-Z0-9_]*)\s*=\s*["']([^"']*)["']""")
# 排除调用式（如 @field_validator("SECRET_KEY", mode="before") 左侧不是赋值变量）
DECORATOR_RE = re.compile(r"^\s*@")


def find_py_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob(f"*{PY_EXT}"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in SKIP_FILES:
            continue
        out.append(p)
    return sorted(out)


def scan_origin_guard(files: list[Path]) -> list[str]:
    """确认整个代码库是否存在 Origin 守卫实现。"""
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if any(g in text for g in ORIGIN_GUARD_HINTS):
            return []  # 已部署全局守卫，通过
    return [
        "整个代码库未发现 Origin 守卫实现（verify_origin / ALLOWED_ORIGINS / "
        "request.headers.get('origin') 等）。敏感端点（登录/改密/OTP）缺少 Login CSRF 防护，"
        "建议在某全局依赖或中间件中实现 Origin 校验。"
    ]


def scan_hardcoded_secrets(files: list[Path]) -> list[str]:
    """返回风险描述列表：疑似硬编码密钥赋值。"""
    findings: list[str] = []
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if DECORATOR_RE.match(line):
                continue  # 跳过装饰器，避免 @field_validator("SECRET_KEY") 误报
            m = ASSIGN_RE.match(line)
            if not m:
                continue
            var, literal = m.group(1), m.group(2)
            if var not in SECRET_VAR_NAMES:
                continue
            if not literal:
                continue  # 空串不算
            if literal in SAFE_LITERAL_WHITELIST:
                continue
            # 排除明显占位
            if literal.strip().lower() in ("change_me", "changeme", "placeholder"):
                continue
            # 排除右侧为 env 读取（已在上面正则之外，这里再兜一层）
            if "os.environ" in line or "getenv" in line:
                continue
            findings.append(f'{f}:{i}: 疑似硬编码密钥 -> {var} = "{literal}"')
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="后端安全静态扫描")
    parser.add_argument("--root", default="app", help="扫描根目录（默认 app）")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"[scan_security] 根目录不存在: {root}", file=sys.stderr)
        return 2

    files = find_py_files(root)
    print(f"[scan_security] 扫描 {len(files)} 个 Python 文件（root={root}）")

    findings: list[str] = []
    findings += scan_origin_guard(files)
    findings += scan_hardcoded_secrets(files)

    if findings:
        print("\n[scan_security] 发现潜在风险：")
        for f in findings:
            print(f"  - {f}")
        print(f"\n共 {len(findings)} 项。请在合并前消除（或经安全评审豁免）。")
        return 1

    print("[scan_security] 未发现高风险模式，通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
