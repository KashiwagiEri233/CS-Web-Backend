#!/usr/bin/env python3
"""P6 身份导入：把 export_identity.py 的 JSON 导入隔离演练库。

安全边界：
    * 只允许写入显式 ``--confirm-target`` 的空演练库；默认拒绝非空表；
    * 导入前校验数据文件 SHA256 与 manifest 一致；
    * 保留原 ID，导入后修复序列；不创建表、不执行 Alembic；
    * 重复导入：内容完全一致则 no-op；任一冲突立即失败，不做覆盖。

用法::

    python tools/scripts/reconstruction/import_identity.py --dry-run \
        --data-file D:\\rebuild\\identity\\identity_xxx.json \
        --manifest-file D:\\rebuild\\identity\\identity_xxx.manifest.json \
        --target-env .env.rebuild --confirm-target domefff_rebuild_test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import psycopg2
except ImportError:  # pragma: no cover
    print("[import-identity] 缺少 psycopg2", file=sys.stderr)
    raise

BACKEND_ROOT = Path(__file__).resolve().parents[3]
IDENTITY_TABLES = ("users", "two_factor_auth", "password_history")


def _primary_key(cur, table: str, columns: List[str]) -> str:
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


def _connect(env_file: Path):
    values = _parse_env_file(env_file)
    url = values.get("DATABASE_URL")
    if url:
        return psycopg2.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    return psycopg2.connect(
        host=values.get("DATABASE_HOST", "127.0.0.1"),
        port=int(values.get("DATABASE_PORT", "5432")),
        dbname=values.get("DATABASE_NAME", ""),
        user=values.get("DATABASE_USER", "postgres"),
        password=values.get("DATABASE_PASSWORD"),
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _table_columns(cur, table: str) -> List[str]:
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
        """,
        (table,),
    )
    return [row[0] for row in cur.fetchall()]


def _row_count(cur, table: str) -> int:
    cur.execute(f'SELECT count(*) FROM public."{table}"')
    return int(cur.fetchone()[0])


def _fetch_rows(cur, table: str, columns: List[str], pk: str) -> List[Dict[str, Any]]:
    col_sql = ", ".join(f'"{c}"' for c in columns)
    cur.execute(f'SELECT {col_sql} FROM public."{table}" ORDER BY "{pk}"')
    return [dict(zip(columns, values)) for values in cur.fetchall()]


def _digest(rows: List[Dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fix_sequence(cur, table: str, column: str) -> None:
    cur.execute(
        "SELECT pg_get_serial_sequence(%s, %s)", (f"public.{table}", column)
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return
    cur.execute(f'SELECT COALESCE(MAX("{column}"), 0) FROM public."{table}"')
    max_id = int(cur.fetchone()[0])
    if max_id > 0:
        cur.execute("SELECT setval(%s, %s, true)", (row[0], max_id))


def _json_columns(cur, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
          AND data_type IN ('json', 'jsonb')
        """,
        (table,),
    )
    return {row[0] for row in cur.fetchall()}


def _insert_rows(
    cur, table: str, rows: List[Dict[str, Any]], columns: List[str], json_cols: set[str]
) -> None:
    col_sql = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f'INSERT INTO public."{table}" ({col_sql}) VALUES ({placeholders})'
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if column in json_cols and value is not None and not isinstance(value, str):
                values.append(json.dumps(value, ensure_ascii=False))
            else:
                values.append(value)
        cur.execute(sql, values)


def main() -> int:
    parser = argparse.ArgumentParser(description="导入官网身份白名单到空演练库")
    parser.add_argument("--data-file", required=True)
    parser.add_argument("--manifest-file", required=True)
    parser.add_argument("--target-env", default=".env.rebuild")
    parser.add_argument("--confirm-target", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default="", help="机器可读报告输出路径")
    args = parser.parse_args()

    data_path = Path(args.data_file)
    manifest_path = Path(args.manifest_file)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if _sha256_file(data_path) != manifest.get("data_file_sha256"):
        print("[import-identity] 数据文件 SHA256 与 manifest 不一致", file=sys.stderr)
        return 2

    for table in IDENTITY_TABLES:
        meta = manifest.get("tables", {}).get(table)
        if not meta:
            print(f"[import-identity] manifest 缺少表 {table}", file=sys.stderr)
            return 2
        if _digest(data.get(table, [])) != meta["sha256"]:
            print(f"[import-identity] {table} 摘要与 manifest 不一致", file=sys.stderr)
            return 2

    conn = _connect(Path(args.target_env))
    report: Dict[str, Any] = {"database": "", "tables": {}, "status": "unknown"}
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            db_name = cur.fetchone()[0]
            report["database"] = db_name
            if args.confirm_target and args.confirm_target != db_name:
                print(
                    f"[import-identity] --confirm-target 不匹配：{args.confirm_target} != {db_name}",
                    file=sys.stderr,
                )
                return 2
            if not args.dry_run and not args.confirm_target:
                print("[import-identity] 非 dry-run 必须提供 --confirm-target", file=sys.stderr)
                return 2

            for table in IDENTITY_TABLES:
                target_columns = _table_columns(cur, table)
                wanted = manifest["tables"][table]["columns"]
                missing = [c for c in wanted if c not in target_columns]
                if missing:
                    print(
                        f"[import-identity] {table} 目标缺列：{missing}（请先 upgrade head）",
                        file=sys.stderr,
                    )
                    return 2
                existing = _row_count(cur, table)
                rows = data.get(table, [])
                report["tables"][table] = {
                    "source": len(rows),
                    "existing": existing,
                }
                if existing:
                    pk = _primary_key(cur, table, target_columns)
                    current = _fetch_rows(cur, table, wanted, pk)
                    if _digest(current) == manifest["tables"][table]["sha256"]:
                        report["tables"][table]["result"] = "identical-noop"
                        continue
                    print(
                        f"[import-identity] {table} 非空且内容不同，拒绝覆盖",
                        file=sys.stderr,
                    )
                    return 3
                if not rows:
                    report["tables"][table]["result"] = "identical-noop"
                    continue
                if args.dry_run:
                    report["tables"][table]["result"] = "would-insert"
                    continue
                _insert_rows(cur, table, rows, wanted, _json_columns(cur, table))
                _fix_sequence(cur, table, _primary_key(cur, table, target_columns))
                report["tables"][table]["result"] = "inserted"

            if args.dry_run:
                conn.rollback()
                report["status"] = "dry-run"
            else:
                conn.commit()
                report["status"] = "committed"
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"[import-identity] 导入失败，已回滚：{exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
