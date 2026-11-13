#!/usr/bin/env python3
"""P6 重建校验：身份摘要、Alembic head、钱包零差异、RBAC 基线。

任何关键不一致以非零退出；报告不含密码哈希或 TOTP 密文。
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
    print("[verify-rebuild] 缺少 psycopg2", file=sys.stderr)
    raise

IDENTITY_TABLES = ("users", "two_factor_auth", "password_history")


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


def _fetch_rows(cur, table: str, columns: List[str], pk: str) -> List[Dict[str, Any]]:
    col_sql = ", ".join(f'"{c}"' for c in columns)
    cur.execute(f'SELECT {col_sql} FROM public."{table}" ORDER BY "{pk}"')
    return [dict(zip(columns, values)) for values in cur.fetchall()]


def _digest(rows: List[Dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _scalar(cur, sql: str) -> int:
    cur.execute(sql)
    return int(cur.fetchone()[0] or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验重建演练库")
    parser.add_argument("--target-env", default=".env.rebuild")
    parser.add_argument("--confirm-target", required=True)
    parser.add_argument("--manifest-file", default="")
    parser.add_argument("--data-file", default="")
    parser.add_argument("--expected-revision", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    failures: List[str] = []
    report: Dict[str, Any] = {"database": "", "checks": {}, "failures": failures}
    conn = _connect(Path(args.target_env))
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            db_name = cur.fetchone()[0]
            report["database"] = db_name
            if db_name != args.confirm_target:
                failures.append(f"目标库不匹配：{db_name} != {args.confirm_target}")

            cur.execute("SELECT version_num FROM alembic_version")
            revisions = [row[0] for row in cur.fetchall()]
            report["checks"]["alembic_revisions"] = revisions
            expected = args.expected_revision
            manifest = None
            if args.manifest_file:
                manifest = json.loads(Path(args.manifest_file).read_text(encoding="utf-8"))
                expected = expected or manifest.get("schema_revision")
            if len(revisions) != 1:
                failures.append(f"alembic_version 应只有一个 head，实际 {revisions}")
            if expected and revisions != [expected]:
                failures.append(f"Alembic head 不一致：{revisions} != {expected}")

            if manifest:
                for table in IDENTITY_TABLES:
                    meta = manifest["tables"][table]
                    columns = meta["columns"]
                    current = _scalar(cur, f'SELECT count(*) FROM public."{table}"')
                    report["checks"][f"{table}_count"] = current
                    if current != meta["row_count"]:
                        failures.append(
                            f"{table} 行数不一致：{current} != {meta['row_count']}"
                        )
                    if args.data_file:
                        pk = _primary_key(cur, table, columns)
                        rows = _fetch_rows(cur, table, columns, pk)
                        if _digest(rows) != meta["sha256"]:
                            failures.append(f"{table} 摘要与 manifest 不一致")

            report["checks"]["negative_balances"] = _scalar(
                cur,
                "SELECT count(*) FROM wallet_accounts "
                "WHERE kind <> 'issuance' AND balance < 0",
            )
            report["checks"]["projection_mismatches"] = _scalar(
                cur,
                """
                SELECT count(*) FROM wallet_accounts a
                LEFT JOIN (
                    SELECT account_id, SUM(delta) AS total FROM ledger_entries GROUP BY account_id
                ) e ON e.account_id = a.id
                WHERE a.balance <> COALESCE(e.total, 0)
                """,
            )
            report["checks"]["unbalanced_transactions"] = _scalar(
                cur,
                """
                SELECT count(*) FROM ledger_transactions t
                LEFT JOIN (
                    SELECT transaction_id, SUM(delta) AS total FROM ledger_entries GROUP BY transaction_id
                ) e ON e.transaction_id = t.id
                WHERE COALESCE(e.total, 0) <> 0
                """,
            )
            report["checks"]["roles"] = _scalar(cur, "SELECT count(*) FROM roles")
            report["checks"]["permissions"] = _scalar(cur, "SELECT count(*) FROM permissions")
            report["checks"]["active_superusers"] = _scalar(
                cur,
                "SELECT count(*) FROM users WHERE is_superuser AND is_active "
                "AND deleted_at IS NULL",
            )
            report["checks"]["member_role_exists"] = _scalar(
                cur, "SELECT count(*) FROM roles WHERE name = 'member'"
            )
            report["checks"]["users_without_member_profile"] = _scalar(
                cur,
                """
                SELECT count(*) FROM users u
                LEFT JOIN member_profiles m ON m.user_id = u.id
                WHERE u.deleted_at IS NULL AND m.id IS NULL
                """,
            )

            for key in ("negative_balances", "projection_mismatches", "unbalanced_transactions"):
                if report["checks"][key] != 0:
                    failures.append(f"{key}={report['checks'][key]}（应为 0）")
            if report["checks"]["member_role_exists"] == 0:
                failures.append("缺少 member 角色（RBAC seed 未执行）")
            if report["checks"]["users_without_member_profile"] != 0:
                failures.append(
                    f"有 {report['checks']['users_without_member_profile']} 个有效用户缺少成员档案"
                )
    finally:
        conn.close()

    report["status"] = "ok" if not failures else "failed"
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
