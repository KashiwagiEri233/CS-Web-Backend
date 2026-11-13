#!/usr/bin/env python3
"""P0 身份导出：按白名单导出官网用户身份与安全资料，并生成脱敏 manifest。

用途：为统一后端重建演练提供可校验、可重放的官网身份快照（原 ID、密码哈希、
OAuth 绑定、2FA 密文、密码历史）。本脚本**只读**，不写源库。

安全边界：
    * 输出目录必须位于四个源码仓库与本方案文档目录之外，且不能在 Git 工作区；
    * 导出文件权限设为仅当前用户可读写（POSIX 0600；Windows 尽力设置 ACL）；
    * manifest 只含库名、版本、行数、列名与 SHA256 摘要，不含密码哈希、TOTP 密文、
      恢复码哈希或任何身份明细；
    * 非 dry-run 必须显式 ``--confirm-target <database>`` 与目标库名一致。

用法::

    # 先看将导出多少行（不写文件）
    python tools/scripts/reconstruction/export_identity.py --dry-run \
        --output-dir D:\\rebuild\\identity --confirm-target domefff

    # 正式导出（目录必须在仓库外）
    python tools/scripts/reconstruction/export_identity.py \
        --output-dir D:\\rebuild\\identity --confirm-target domefff
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import psycopg2
except ImportError:  # pragma: no cover
    print("[export-identity] 缺少 psycopg2", file=sys.stderr)
    raise

BACKEND_ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_ROOTS = [
    BACKEND_ROOT,
    Path(r"C:\Users\admin\Desktop\CS-Web-Frontend"),
    Path(r"C:\Users\admin\Desktop\FGS_CS_B"),
    Path(r"C:\Users\admin\Desktop\FGS_CS_F"),
    Path(r"C:\Users\admin\Desktop\CS-Web-Task-Integration"),
]

# 保留白名单：仅身份与安全资料；不导出任务、积分、业务历史。
IDENTITY_TABLES = {
    "users": (
        "id, username, email, hashed_password, full_name, display_name, bio, "
        "avatar_url, avatar_type, github_url, website_url, github_id, "
        "is_active, is_superuser, password_changed_at, deleted_at, "
        "created_at, updated_at, sync_id, tech_tags"
    ),
    "two_factor_auth": None,  # 运行时按 information_schema 取列
    "password_history": None,
}


def _parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _conn_params(env_file: Path) -> Dict[str, Any]:
    values = _parse_env_file(env_file)
    url = values.get("DATABASE_URL")
    if url:
        return {
            "dsn": url.replace("postgresql+asyncpg://", "postgresql://"),
            "name": "",
        }
    return {
        "host": values.get("DATABASE_HOST", "127.0.0.1"),
        "port": int(values.get("DATABASE_PORT", "5432")),
        "dbname": values.get("DATABASE_NAME", "domefff"),
        "user": values.get("DATABASE_USER", "postgres"),
        "password": values.get("DATABASE_PASSWORD"),
    }


def _connect(params: Dict[str, Any]):
    dsn = params.pop("dsn", None)
    params.pop("name", None)
    conn = psycopg2.connect(dsn) if dsn else psycopg2.connect(**params)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _assert_output_dir_allowed(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    for root in FORBIDDEN_ROOTS:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        raise SystemExit(
            f"[export-identity] 拒绝写入仓库/文档目录：{resolved}（禁止根目录 {root}）"
        )
    # 拒绝位于任何 Git 工作区内（向上查找 .git）
    for parent in [resolved, *resolved.parents]:
        if (parent / ".git").exists():
            raise SystemExit(
                f"[export-identity] 输出目录位于 Git 工作区：{parent}；请改用受限备份目录"
            )


def _table_columns(cur, table: str) -> List[str]:
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
        """,
        (table,),
    )
    return [r[0] for r in cur.fetchall()]


def _order_column(cur, table: str, columns: List[str]) -> str:
    """稳定排序键：优先主键首列，否则退回首列（保证摘要可重放）。"""
    cur.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = tc.constraint_name
         AND kcu.table_schema = tc.table_schema
        WHERE tc.table_schema='public' AND tc.table_name=%s
          AND tc.constraint_type='PRIMARY KEY'
        ORDER BY kcu.ordinal_position
        LIMIT 1
        """,
        (table,),
    )
    row = cur.fetchone()
    if row and row[0] in columns:
        return row[0]
    return columns[0]


def _fetch_rows(cur, table: str, columns: List[str]) -> List[Dict[str, Any]]:
    col_sql = ", ".join(f'"{c}"' for c in columns)
    order_col = _order_column(cur, table, columns)
    cur.execute(f'SELECT {col_sql} FROM public."{table}" ORDER BY "{order_col}"')
    rows = cur.fetchall()
    return [dict(zip(columns, values)) for values in rows]


def _digest(rows: List[Dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _restrict_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if os.name == "nt":
        # Windows 上 chmod 语义有限；尽力移除继承并仅保留当前用户。
        try:
            import subprocess

            user = os.environ.get("USERNAME", "")
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", f"/grant:r", f"{user}:(R,W)"],
                check=False,
                capture_output=True,
            )
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="导出官网身份白名单并生成 manifest")
    parser.add_argument("--official-env", default=".env.development")
    parser.add_argument("--output-dir", required=True, help="受限备份目录（仓库外）")
    parser.add_argument(
        "--confirm-target",
        default="",
        help="必须与目标库名完全一致；非 dry-run 时必填",
    )
    parser.add_argument("--dry-run", action="store_true", help="只输出计数，不写文件")
    parser.add_argument(
        "--exclude-security",
        action="store_true",
        help="不导出 2FA/密码历史（默认导出，便于身份完整保留）",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    _assert_output_dir_allowed(output_dir)

    params = _conn_params(Path(args.official_env))
    conn = _connect(dict(params))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            db_name = cur.fetchone()[0]
            if not args.dry_run and args.confirm_target != db_name:
                raise SystemExit(
                    "[export-identity] --confirm-target 与目标库名不一致，已拒绝导出"
                )
            cur.execute(
                "SELECT version_num FROM alembic_version" if _has_alembic(cur) else "SELECT NULL"
            )
            revision = (cur.fetchone() or [None])[0]

            tables = ["users"]
            if not args.exclude_security:
                tables.extend(["two_factor_auth", "password_history"])

            export: Dict[str, Any] = {
                "manifest": {
                    "database": db_name,
                    "schema_revision": revision,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "tables": {},
                },
                "data": {},
            }
            for table in tables:
                columns = _table_columns(cur, table)
                rows = _fetch_rows(cur, table, columns)
                export["data"][table] = rows
                export["manifest"]["tables"][table] = {
                    "columns": columns,
                    "row_count": len(rows),
                    "sha256": _digest(rows),
                }

            avatars = [
                row.get("avatar_url")
                for row in export["data"]["users"]
                if row.get("avatar_url")
            ]
            export["manifest"]["avatar_reference_count"] = len(avatars)

            if args.dry_run:
                for table, meta in export["manifest"]["tables"].items():
                    print(f"[dry-run] {table}: {meta['row_count']} 行")
                print("[dry-run] 未写入任何文件")
                return 0

            output_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            data_path = output_dir / f"identity_{stamp}.json"
            manifest_path = output_dir / f"identity_{stamp}.manifest.json"

            buffer = io.StringIO()
            json.dump(export["data"], buffer, ensure_ascii=False, default=str)
            content = buffer.getvalue()
            data_path.write_text(content, encoding="utf-8")
            _restrict_permissions(data_path)

            export["manifest"]["data_file_sha256"] = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(export["manifest"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _restrict_permissions(manifest_path)

            print(f"[export-identity] 数据文件：{data_path}")
            print(f"[export-identity] manifest：{manifest_path}")
            for table, meta in export["manifest"]["tables"].items():
                print(f"[export-identity] {table}: {meta['row_count']} 行")
            return 0
    finally:
        conn.close()


def _has_alembic(cur) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema='public' AND table_name='alembic_version'
        """
    )
    return cur.fetchone() is not None


if __name__ == "__main__":
    raise SystemExit(main())
