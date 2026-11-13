#!/usr/bin/env python3
"""契约门禁：当前后端 OpenAPI 必须与两端基线完全一致。

用途：CI / 交付前检查。任何路径、方法或字段差异都以非零退出，
并输出新增/删除的端点清单，避免两端在不知情的情况下漂移。

用法::

    python tools/scripts/reconstruction/check_contracts.py
    python tools/scripts/reconstruction/check_contracts.py --report contract-drift.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DESKTOP = BACKEND_ROOT.parent
TARGETS = [
    DESKTOP / "CS-Web-Frontend",
    DESKTOP / "FGS_CS_F",
]


def _endpoints(spec: dict) -> Set[str]:
    result: Set[str] = set()
    for path, methods in (spec.get("paths") or {}).items():
        for method in methods:
            if method.lower() in {"get", "post", "put", "patch", "delete"}:
                result.add(f"{method.upper()} {path}")
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="校验两端 OpenAPI 基线与当前契约一致")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    exporter = BACKEND_ROOT / "tools" / "scripts" / "contract" / "export_openapi.py"
    current_path = BACKEND_ROOT / ".openapi.check.tmp.json"
    proc = subprocess.run(
        [sys.executable, str(exporter), "--baseline", str(current_path)],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not current_path.exists():
        print("[check-contracts] 无法导出当前契约：", proc.stderr, file=sys.stderr)
        current_path.unlink(missing_ok=True)
        return 1

    current_bytes = current_path.read_bytes()
    current_sha = hashlib.sha256(current_bytes).hexdigest()
    current_spec = json.loads(current_bytes)
    current_endpoints = _endpoints(current_spec)

    report: Dict[str, object] = {
        "status": "ok",
        "route_count": len(current_endpoints),
        "sha256": current_sha,
        "targets": {},
        "drift": [],
    }
    failed = False

    for repo in TARGETS:
        if not repo.exists():
            continue
        baseline = repo / "openapi.baseline.json"
        meta = repo / "contract-meta.json"
        entry: Dict[str, object] = {"baseline": str(baseline), "present": baseline.exists()}
        if not baseline.exists():
            entry["result"] = "missing-baseline"
            failed = True
            report["drift"].append(f"{repo.name}: 缺少 openapi.baseline.json")
        else:
            baseline_sha = _sha256(baseline)
            entry["baseline_sha256"] = baseline_sha
            if baseline_sha != current_sha:
                entry["result"] = "drift"
                failed = True
                baseline_spec = json.loads(baseline.read_bytes())
                baseline_endpoints = _endpoints(baseline_spec)
                added = sorted(current_endpoints - baseline_endpoints)
                removed = sorted(baseline_endpoints - current_endpoints)
                entry["added"] = added
                entry["removed"] = removed
                report["drift"].append(
                    {
                        "repo": repo.name,
                        "added": added,
                        "removed": removed,
                    }
                )
            else:
                entry["result"] = "match"
            if meta.exists():
                meta_data = json.loads(meta.read_text(encoding="utf-8"))
                entry["meta_sha256_matches"] = meta_data.get("sha256") == baseline_sha
                if not entry["meta_sha256_matches"]:
                    failed = True
                    report["drift"].append(f"{repo.name}: contract-meta.json 与基线 SHA 不一致")
        report["targets"][repo.name] = entry

    current_path.unlink(missing_ok=True)
    report["status"] = "failed" if failed else "ok"

    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
