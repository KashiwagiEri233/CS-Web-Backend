#!/usr/bin/env python3
"""导出 /api/v1 OpenAPI 契约并与基线比对（G3：冻结契约门禁）。

用法：
    # 生成/更新基线（审批后执行）：
    python scripts/export_openapi.py --baseline > openapi.baseline.json
    # 或：make contract-baseline

    # 比对当前契约与基线（CI 门禁，发现差异即非零退出）：
    python scripts/export_openapi.py --check openapi.baseline.json
    # 或：make contract-check

说明：
    - 直接 import app.main:app 后在进程内调用 app.openapi()，无需启动服务、无需数据库。
    - 仅导出 /api/v1 前缀的路由（API_V1_STR），冻结业务契约。
    - 比对忽略 servers/info/version 等易变字段，聚焦 path / method / 参数 / schema。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 将后端仓库根加入 sys.path，使脚本可独立运行（不依赖外部 PYTHONPATH）。
# 脚本位于 tools/scripts/contract/ 下，向上若干级到达仓库根；
# 用「直到找到 pyproject.toml」兜底，避免目录层级变动导致路径错位
#（此前写死 .parent.parent.parent 在脚本移入 contract/ 子目录后少算一级，
# 致 `from app.main import app` 失败、契约门禁实质上从未跑通）。
_BACKEND_ROOT = Path(__file__).resolve().parent
while not (_BACKEND_ROOT / "pyproject.toml").exists():
    parent = _BACKEND_ROOT.parent
    if parent == _BACKEND_ROOT:
        break
    _BACKEND_ROOT = parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# 最小环境变量，避免导入期因缺失密钥报错（schema 生成不需要真实密钥）。

os.environ.setdefault("SECRET_KEY", "contract-export-placeholder-32bytes-minimum")
os.environ.setdefault("TOTP_ENCRYPTION_KEY", "contract-export-placeholder-32bytes-min")
os.environ.setdefault("AUTH_SESSION_SECRET", "contract-export-session-secret-32bytes-min")
os.environ.setdefault("COMMUNITY_IP_HASH_SECRET", "contract-export-community-hash-secret-32")
os.environ.setdefault("DATABASE_PASSWORD", "contract-export")
os.environ.setdefault("AUTH_ENABLED", "true")


def _load_app():
    # 在导入 app 前先移除 loguru 默认 sink，避免 import 期日志污染 stdout/stdout。
    # 注意：app.main 的 import 会触发 init_logging 重新挂 sink，这里仅尽力而为；
    # 真正的纯净输出由「写文件」而非「写 stdout」保证（见 main()）。
    try:
        from loguru import logger

        logger.remove()
    except Exception:
        pass

    from app.main import app  # 延迟导入，确保 env 已设

    return app


def export_spec() -> dict:
    app = _load_app()
    from app.core.config import settings

    spec = app.openapi()
    # 仅保留 /api/v1 路由，冻结业务契约范围
    v1_prefix = settings.API_V1_STR  # 形如 /api/v1
    paths = {p: d for p, d in spec.get("paths", {}).items() if p.startswith(v1_prefix)}
    spec = dict(spec)
    spec["paths"] = paths
    # 移除易变字段，避免无意义 diff（servers 不参与契约判定）
    spec.pop("servers", None)
    info = dict(spec.get("info", {}))
    # 写入四源版本（app/__init__.py __version__），保留「四源版本 → 冻结契约」追溯链；
    # 比对侧 (check_spec) 仍忽略 info.version，不参与契约差异判定（见下方 check 分支）。
    from app import __version__ as app_version
    info["version"] = app_version
    spec["info"] = info
    return spec


def _normalize(spec: dict) -> str:
    return json.dumps(spec, sort_keys=True, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="导出/比对 /api/v1 OpenAPI 契约")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--baseline",
        nargs="?",
        const="openapi.baseline.json",
        metavar="OUTPUT_JSON",
        help="导出当前契约为基线（纯 JSON 写入文件，默认 openapi.baseline.json）",
    )
    group.add_argument(
        "--check",
        metavar="BASELINE_JSON",
        help="将当前契约与指定基线文件比对，差异则退出码 1",
    )
    args = parser.parse_args()

    current = export_spec()

    if args.baseline:
        out_path = Path(args.baseline)
        out_path.write_text(_normalize(current), encoding="utf-8")
        print(
            f"[contract-baseline] 已写入基线：{out_path}"
            f"（{len(current['paths'])} 个 /api/v1 路由）"
        )
        return 0

    baseline_path = Path(args.check)
    if not baseline_path.exists():
        print(f"[contract-check] 基线文件不存在：{baseline_path}", file=sys.stderr)
        return 2

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    # 与生成侧一致：比对时忽略 info.version（基线文件保留 version 用于人工追溯，
    # 但 version 不参与契约差异判定，避免「四源版本」更新引发无意义 diff）。
    # 当前契约与基线对称剥离，否则导出侧写入的 version 会导致比对恒不等。
    baseline_info = dict(baseline.get("info", {}))
    baseline_info.pop("version", None)
    baseline["info"] = baseline_info
    cur_info = dict(current.get("info", {}))
    cur_info.pop("version", None)
    current["info"] = cur_info
    cur = json.loads(_normalize(current))
    base = json.loads(_normalize(baseline))

    if cur == base:
        print("[contract-check] OK：当前契约与基线一致。")
        return 0

    # 计算差异摘要
    added = sorted(set(cur["paths"]) - set(base["paths"]))
    removed = sorted(set(base["paths"]) - set(cur["paths"]))
    print("[contract-check] 契约发生变化（需评审并更新基线）：", file=sys.stderr)
    if added:
        print(f"  新增路由: {added}", file=sys.stderr)
    if removed:
        print(f"  移除路由: {removed}", file=sys.stderr)
    # 路由级变更（同 path 但 method/参数/schema 不同）
    changed = []
    for p in set(cur["paths"]) & set(base["paths"]):
        if cur["paths"][p] != base["paths"][p]:
            changed.append(p)
    if changed:
        print(f"  变更路由: {sorted(changed)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
