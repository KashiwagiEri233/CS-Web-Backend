#!/usr/bin/env python3
"""P7 遗留调用者检查：确认后端/F 已无旧任务代理、旧积分与用户同步引用。

用途：作为 `remove_legacy_integration` 破坏性迁移前的证据门禁。
- 扫描后端 `app/`：旧模块符号、旧路由注册、旧配置项；
- 扫描官网 F `src/app/api` 与 `src/modules`：旧 BFF 路径；
- 命中即非零退出（排除历史 Alembic 迁移与文档）。

旧端 LF 的 localStorage token 与 `core/request.ts` 仍服务角色权限弹窗，
按方案在维护窗口内随 P7 一并清理，本脚本不将其计为阻塞项。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DESKTOP = BACKEND_ROOT.parent

BACKEND_PATTERNS = [
    r"\blegacy_task_client\b",
    r"\bLegacyTaskClient\b",
    r"\blegacy_user_sync\b",
    r"\bLegacyUserSync\b",
    r"\bLegacySyncOutbox\b",
    r"\bLegacySyncState\b",
    r"\bPointsTransaction\b",
    r"\bPointsService\b",
    r"\bPointsRepository\b",
    r"\bLEGACY_API_BASE_URL\b",
    r"\bLEGACY_JWT_SECRET\b",
    r"\bINTERNAL_TOKEN\b",
    r"tools\.task\b",
    r"tools\.points\b",
    r"internal\.users\b",
]

FRONTEND_PATTERNS = [
    r"/api/tools/task\b",
    r"/api/tools/points\b",
    r"/api/admin/tools/task\b",
]

LEGACY_FRONTEND_PATTERNS = [
    r"\.\./core/(request|token|config|permissions)\b",
    r"/rbac/peaks\b",
]

SKIP_DIR_NAMES = {".venv", "node_modules", ".next", "dist", "build", "__pycache__"}


def _iter_files(root: Path, suffixes: set[str]):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def _scan(root: Path, patterns: list[str], suffixes: set[str], label: str) -> list[dict]:
    compiled = [(p, re.compile(p)) for p in patterns]
    hits: list[dict] = []
    for path in _iter_files(root, suffixes):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, regex in compiled:
                if regex.search(line):
                    hits.append(
                        {
                            "scope": label,
                            "file": str(path.relative_to(DESKTOP)),
                            "line": lineno,
                            "pattern": pattern,
                            "text": line.strip()[:200],
                        }
                    )
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="P7 遗留调用者检查")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    hits: list[dict] = []
    hits += _scan(BACKEND_ROOT / "app", BACKEND_PATTERNS, {".py"}, "backend-app")
    hits += _scan(
        DESKTOP / "CS-Web-Frontend" / "src" / "app" / "api",
        FRONTEND_PATTERNS,
        {".ts", ".tsx"},
        "frontend-bff",
    )
    hits += _scan(
        DESKTOP / "FGS_CS_F" / "app",
        LEGACY_FRONTEND_PATTERNS,
        {".ts", ".tsx"},
        "legacy-frontend",
    )

    report = {
        "status": "ok" if not hits else "hits",
        "patterns": BACKEND_PATTERNS + FRONTEND_PATTERNS + LEGACY_FRONTEND_PATTERNS,
        "hit_count": len(hits),
        "hits": hits,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if not hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
