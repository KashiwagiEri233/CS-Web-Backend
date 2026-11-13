#!/usr/bin/env python3
"""P0 只读盘点：官网库与旧库的结构、行数、对象分类。

严格只读：连接后设置 ``default_transaction_read_only=on``，不建表、不写数据。
报告只输出库名、主机、结构与计数，不输出密码、密码哈希、TOTP 密钥或身份明细。

用法::

    # 同时盘点官网库与旧库（旧库配置从 FGS_CS_B/.env 读取）
    python tools/scripts/reconstruction/inventory.py

    # 只盘点官网库，并写出 JSON 结构快照
    python tools/scripts/reconstruction/inventory.py --target official \
        --output C:\\Users\\admin\\reports\\inventory.json

环境变量/文件：
    --official-env   官网库配置（默认 .env.development）
    --legacy-env     旧库配置（默认 C:\\Users\\admin\\Desktop\\FGS_CS_B\\.env）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import psycopg2
except ImportError:  # pragma: no cover - 仅在缺依赖时提示
    print("[inventory] 缺少 psycopg2，请先安装数据库驱动", file=sys.stderr)
    raise

# 附录 B.1 声明的旧库 13 张表；不在其中的对象一律标记为 unknown，禁止自动清理。
LEGACY_KNOWN_TABLES = {
    "users",
    "roles",
    "permissions",
    "role_permissions",
    "user_roles",
    "audit_logs",
    "tasks",
    "disciples",
    "peaks",
    "lingshi_transactions",
    "announcements",
    "events",
    "event_participants",
}

LEGACY_ENV_KEYS = {
    "host": "DB_HOST",
    "port": "DB_PORT",
    "name": "DB_NAME",
    "user": "DB_USERNAME",
    "password": "DB_PASSWORD",
}


def _parse_env_file(path: Path) -> Dict[str, str]:
    """解析简单 KEY=VALUE 配置；忽略注释与空行。"""
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


def _official_conn_params(env_file: Path) -> Dict[str, Any]:
    values = _parse_env_file(env_file)
    url = values.get("DATABASE_URL")
    if url:
        return {"dsn": url.replace("postgresql+asyncpg://", "postgresql://"), "name": ""}
    return {
        "host": values.get("DATABASE_HOST", "127.0.0.1"),
        "port": int(values.get("DATABASE_PORT", "5432")),
        "dbname": values.get("DATABASE_NAME", "domefff"),
        "user": values.get("DATABASE_USER", "postgres"),
        "password": values.get("DATABASE_PASSWORD"),
        "name": values.get("DATABASE_NAME", "domefff"),
    }


def _legacy_conn_params(env_file: Path) -> Dict[str, Any]:
    values = _parse_env_file(env_file)
    return {
        "host": values.get(LEGACY_ENV_KEYS["host"], "127.0.0.1"),
        "port": int(values.get(LEGACY_ENV_KEYS["port"], "5432")),
        "dbname": values.get(LEGACY_ENV_KEYS["name"], "postgres"),
        "user": values.get(LEGACY_ENV_KEYS["user"], "postgres"),
        "password": values.get(LEGACY_ENV_KEYS["password"]),
        "name": values.get(LEGACY_ENV_KEYS["name"], "postgres"),
    }


def _connect(params: Dict[str, Any]):
    dsn = params.pop("dsn", None)
    params.pop("name", None)
    conn = psycopg2.connect(dsn) if dsn else psycopg2.connect(**params)
    # 只读事务 + 自动提交，确保任何意外 UPDATE 都会被数据库拒绝。
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _fetch_all(cur, sql: str, args: tuple = ()) -> List[tuple]:
    cur.execute(sql, args)
    return cur.fetchall()


def _table_names(cur) -> List[str]:
    rows = _fetch_all(
        cur,
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
    )
    return [r[0] for r in rows]


def _columns(cur, table: str) -> List[Dict[str, Any]]:
    rows = _fetch_all(
        cur,
        """
        SELECT column_name, data_type, udt_name, is_nullable, column_default,
               character_maximum_length, numeric_precision
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
        """,
        (table,),
    )
    return [
        {
            "name": r[0],
            "type": r[1],
            "udt": r[2],
            "nullable": r[3] == "YES",
            "default": r[4],
            "max_length": r[5],
            "precision": r[6],
        }
        for r in rows
    ]


def _constraints(cur, table: str) -> List[Dict[str, str]]:
    rows = _fetch_all(
        cur,
        """
        SELECT c.conname, c.contype, pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname='public' AND t.relname=%s
        ORDER BY c.conname
        """,
        (table,),
    )
    return [{"name": r[0], "type": r[1], "definition": r[2]} for r in rows]


def _indexes(cur, table: str) -> List[Dict[str, Any]]:
    rows = _fetch_all(
        cur,
        """
        SELECT indexname, indexdef FROM pg_indexes
        WHERE schemaname='public' AND tablename=%s
        ORDER BY indexname
        """,
        (table,),
    )
    return [{"name": r[0], "definition": r[1]} for r in rows]


def _row_count(cur, table: str) -> Optional[int]:
    if not table.replace("_", "").isalnum():
        return None
    cur.execute(f'SELECT count(*) FROM public."{table}"')
    return int(cur.fetchone()[0])


def _safe_int(value: Any) -> Any:
    return int(value) if value is not None else None


def _collect_database(
    params: Dict[str, Any],
    known_tables: Optional[set],
    include_counts: bool,
) -> Dict[str, Any]:
    name = params.get("name", "")
    conn = _connect(dict(params))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), version()")
            db_name, server_version = cur.fetchone()
            cur.execute("SELECT extname FROM pg_extension ORDER BY extname")
            extensions = [r[0] for r in cur.fetchall()]
            cur.execute(
                "SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"
            )
            sequences = [r[0] for r in cur.fetchall()]
            cur.execute(
                """
                SELECT trigger_name, event_object_table
                FROM information_schema.triggers
                WHERE trigger_schema='public'
                ORDER BY event_object_table, trigger_name
                """
            )
            triggers = [{"name": r[0], "table": r[1]} for r in cur.fetchall()]

            tables: Dict[str, Any] = {}
            total_rows = 0
            for table in _table_names(cur):
                entry: Dict[str, Any] = {
                    "columns": _columns(cur, table),
                    "constraints": _constraints(cur, table),
                    "indexes": _indexes(cur, table),
                }
                if include_counts:
                    try:
                        entry["row_count"] = _row_count(cur, table)
                        total_rows += entry["row_count"] or 0
                    except Exception as exc:  # noqa: BLE001
                        entry["row_count_error"] = str(exc)
                entry["classification"] = (
                    "unknown"
                    if known_tables is None
                    else ("known" if table in known_tables else "unknown")
                )
                tables[table] = entry

            alembic_rev = None
            if "alembic_version" in tables:
                cur.execute("SELECT version_num FROM alembic_version")
                row = cur.fetchone()
                alembic_rev = row[0] if row else None
    finally:
        conn.close()

    return {
        "database": db_name,
        "host": params.get("host", "dsn"),
        "alembic_revision": alembic_rev,
        "server_version": server_version,
        "extensions": extensions,
        "sequences": sequences,
        "triggers": triggers,
        "table_count": len(tables),
        "total_rows": total_rows,
        "tables": tables,
    }


def _official_model_tables() -> Optional[set]:
    """读取 ORM 模型表名用于分类；导入失败时返回 None（不阻断盘点）。"""
    root = Path(__file__).resolve()
    while not (root / "pyproject.toml").exists() and root.parent != root:
        root = root.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("ENV_FILE", ".env.development")
    os.environ.setdefault("SECRET_KEY", "inventory-placeholder-key-32-bytes-min")
    os.environ.setdefault("TOTP_ENCRYPTION_KEY", "inventory-placeholder-totp-32-bytes")
    os.environ.setdefault(
        "COMMUNITY_IP_HASH_SECRET", "inventory-placeholder-community-hash"
    )
    os.environ.setdefault("DATABASE_PASSWORD", "inventory-readonly")
    try:
        from app.models import Base

        return set(Base.metadata.tables.keys())
    except Exception as exc:  # noqa: BLE001
        print(f"[inventory] ORM 表名分类跳过：{exc}", file=sys.stderr)
        return None


def _markdown(report: Dict[str, Any]) -> str:
    lines = ["# 数据库只读盘点", ""]
    lines.append(f"- 生成时间（UTC）：{report['generated_at']}")
    lines.append(f"- 主机：{report['host']}")
    lines.append("")
    for key, db in report["databases"].items():
        lines.append(f"## {key}：{db['database']}")
        lines.append("")
        lines.append(f"- 表数量：{db['table_count']}")
        lines.append(f"- 总行数：{db.get('total_rows', '未统计')}")
        lines.append(f"- Alembic 版本：{db.get('alembic_revision')}")
        lines.append(f"- 扩展：{', '.join(db['extensions']) or '无'}")
        lines.append("")
        unknown = [t for t, v in db["tables"].items() if v["classification"] == "unknown"]
        if unknown:
            lines.append(f"- 未识别对象（禁止自动清理）：{', '.join(unknown)}")
            lines.append("")
        rows = sorted(
            ((t, v.get("row_count")) for t, v in db["tables"].items()),
            key=lambda item: (-(item[1] or 0), item[0]),
        )
        lines.append("| 表 | 行数 | 分类 |")
        lines.append("|---|---|---|")
        for table, count in rows:
            lines.append(
                f"| {table} | {count if count is not None else 'n/a'} | "
                f"{db['tables'][table]['classification']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 只读盘点官网库与旧库")
    parser.add_argument(
        "--target", choices=["official", "legacy", "both"], default="both"
    )
    parser.add_argument("--official-env", default=".env.development")
    parser.add_argument(
        "--legacy-env", default=r"C:\Users\admin\Desktop\FGS_CS_B\.env"
    )
    parser.add_argument("--output", help="JSON 输出文件；省略则只打印 Markdown 摘要")
    parser.add_argument(
        "--no-counts", action="store_true", help="跳过逐表精确行数统计"
    )
    args = parser.parse_args()

    targets = ["official", "legacy"] if args.target == "both" else [args.target]
    databases: Dict[str, Any] = {}
    if "official" in targets:
        databases["official"] = _collect_database(
            _official_conn_params(Path(args.official_env)),
            _official_model_tables(),
            not args.no_counts,
        )
    if "legacy" in targets:
        databases["legacy"] = _collect_database(
            _legacy_conn_params(Path(args.legacy_env)),
            LEGACY_KNOWN_TABLES,
            not args.no_counts,
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": "127.0.0.1",
        "databases": databases,
    }
    markdown = _markdown(report)
    print(markdown)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[inventory] JSON 已写入：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
