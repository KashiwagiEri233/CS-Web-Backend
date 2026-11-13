#!/usr/bin/env python3
"""P6/P5 契约发布：导出 OpenAPI 基线并同步到两端，生成 SHA256 元数据。

只更新声明目标：CS-Web-Frontend/openapi.baseline.json、
FGS_CS_F/openapi.baseline.json 与对应 contract-meta.json。
不自动运行前端类型生成（需在目标仓库执行 npm run gen:api-types）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DESKTOP = BACKEND_ROOT.parent
TARGETS = [
    DESKTOP / "CS-Web-Frontend" / "openapi.baseline.json",
    DESKTOP / "FGS_CS_F" / "openapi.baseline.json",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="导出并同步 OpenAPI 契约")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    exporter = BACKEND_ROOT / "tools" / "scripts" / "contract" / "export_openapi.py"
    tmp = BACKEND_ROOT / ".openapi.publish.tmp.json"
    proc = subprocess.run(
        [sys.executable, str(exporter), "--baseline", str(tmp)],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not tmp.exists():
        print("[publish-contracts] 导出失败：", proc.stderr, file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return 1

    payload = json.loads(tmp.read_text(encoding="utf-8"))
    route_count = sum(len(methods) for methods in payload.get("paths", {}).values())
    sha = _sha256(tmp)
    report = {
        "status": "dry-run" if args.dry_run else "published",
        "route_count": route_count,
        "sha256": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "targets": [],
    }
    if not args.dry_run:
        for target in TARGETS:
            if not target.parent.exists():
                continue
            target.write_bytes(tmp.read_bytes())
            meta = target.with_name("contract-meta.json")
            meta.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            report["targets"].append(str(target))
    tmp.unlink(missing_ok=True)

    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
