#!/usr/bin/env python3
"""P6 迁移中断演练：在隔离库强制中断 `alembic upgrade`，验证可安全重跑。

流程：
1. 重建隔离库（库名必须含 test/rebuild；需 --confirm-target）；
2. 完整 upgrade head 一次，记录耗时与 head；
3. 再次重建空库，在约半程处 kill 迁移进程；
4. 校验中断后的库状态（版本表/关键表，允许回落到空库）；
5. 重新 upgrade head 至完成，校验 head 与关键表，记录恢复耗时；
6. 输出 JSON 报告（默认写入仓库外 D:\\00025927xiangmu\\rebuild，避免污染源码）。

不连接开发/生产库；中断只发生在隔离演练库。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg2

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env.development"
DEFAULT_REPORT = Path(r"D:\00025927xiangmu\rebuild\migration_interrupt_report.json")

KEY_TABLES = ("users", "wallet_accounts", "ledger_transactions", "tasks", "member_profiles")


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


def _admin_conn(values: Dict[str, str]):
    """连接维护库 postgres，用于重建隔离库。"""
    if values.get("DATABASE_URL"):
        parts = urlsplit(values["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
        return psycopg2.connect(
            host=parts.hostname or "127.0.0.1",
            port=parts.port or 5432,
            dbname="postgres",
            user=parts.username or "postgres",
            password=parts.password or "",
        )
    return psycopg2.connect(
        host=values.get("DATABASE_HOST", "127.0.0.1"),
        port=int(values.get("DATABASE_PORT", "5432")),
        dbname="postgres",
        user=values.get("DATABASE_USER", "postgres"),
        password=values.get("DATABASE_PASSWORD", ""),
    )


def _database_url(
    values: Dict[str, str], database: str, *, async_driver: bool = True
) -> str:
    """构造目标库 URL；alembic/app 需要 asyncpg，psycopg2 校验需要同步驱动。"""
    scheme = "postgresql+asyncpg" if async_driver else "postgresql"
    if values.get("DATABASE_URL"):
        parts = urlsplit(values["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
        return urlunsplit((scheme, parts.netloc, f"/{database}", "", ""))
    user = quote(values.get("DATABASE_USER", "postgres"))
    password = quote(values.get("DATABASE_PASSWORD", ""))
    host = values.get("DATABASE_HOST", "127.0.0.1")
    port = values.get("DATABASE_PORT", "5432")
    return f"{scheme}://{user}:{password}@{host}:{port}/{database}"


def _recreate_database(values: Dict[str, str], database: str) -> None:
    conn = _admin_conn(values)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{database}"')
    finally:
        conn.close()


def _alembic_head(env_file: Path) -> str:
    env = os.environ.copy()
    env["ENV_FILE"] = str(env_file)
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in proc.stdout.splitlines():
        if "(head)" in line:
            return line.split(" ")[0].strip()
    raise RuntimeError(f"无法解析 alembic heads 输出: {proc.stdout} {proc.stderr}")


def _run_upgrade(
    values: Dict[str, str], database: str, env_file: Path, timeout: Optional[float]
) -> Tuple[str, float, str]:
    """执行 upgrade head；timeout 秒后强制终止。返回 (状态, 耗时, 输出尾部)。"""
    env = os.environ.copy()
    env["ENV_FILE"] = str(env_file)
    env["DATABASE_URL"] = _database_url(values, database)
    started = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if timeout is None:
        out, _ = proc.communicate()
        elapsed = time.perf_counter() - started
        status = "ok" if proc.returncode == 0 else f"failed({proc.returncode})"
        return status, elapsed, (out or "")[-2000:]

    try:
        out, _ = proc.communicate(timeout=timeout)
        elapsed = time.perf_counter() - started
        status = "ok" if proc.returncode == 0 else f"failed({proc.returncode})"
        return status, elapsed, (out or "")[-2000:]
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        elapsed = time.perf_counter() - started
        return "interrupted", elapsed, (out or "")[-2000:]


def _db_state(values: Dict[str, str], database: str) -> Dict[str, Any]:
    """读取隔离库当前版本与关键表数量。"""
    conn = psycopg2.connect(_database_url(values, database, async_driver=False))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.alembic_version')")
            has_version = cur.fetchone()[0] is not None
            revision = None
            if has_version:
                cur.execute("SELECT version_num FROM public.alembic_version")
                row = cur.fetchone()
                revision = row[0] if row else None
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
            table_count = int(cur.fetchone()[0])
            present = []
            for name in KEY_TABLES:
                cur.execute("SELECT to_regclass(%s)", (f"public.{name}",))
                if cur.fetchone()[0] is not None:
                    present.append(name)
            return {
                "has_alembic_version": has_version,
                "revision": revision,
                "table_count": table_count,
                "key_tables_present": present,
            }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移中断演练（隔离库）")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--database", default="domefff_rebuild_interrupt")
    parser.add_argument("--confirm-target", action="store_true")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    env_file = Path(args.env_file)
    values = _parse_env_file(env_file)
    database = args.database
    if "test" not in database.lower() and "rebuild" not in database.lower():
        print("[drill] 拒绝执行：库名必须包含 test/rebuild", file=sys.stderr)
        return 2
    dev_db = values.get("DATABASE_NAME", "")
    if database == dev_db:
        print("[drill] 拒绝执行：目标库与开发库同名", file=sys.stderr)
        return 2
    if not args.confirm_target:
        print("[drill] 拒绝执行：缺少 --confirm-target", file=sys.stderr)
        return 2

    head = _alembic_head(env_file)
    report: Dict[str, Any] = {
        "database": database,
        "head": head,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": {},
    }

    # 1) 完整迁移耗时基线
    _recreate_database(values, database)
    status, elapsed, tail = _run_upgrade(values, database, env_file, timeout=None)
    full_state = _db_state(values, database)
    report["steps"]["full_upgrade"] = {
        "status": status,
        "seconds": round(elapsed, 3),
        "state": full_state,
        "output_tail": tail,
    }
    if status != "ok" or full_state["revision"] != head:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 3

    # 2) 清空后在半程处强制中断
    _recreate_database(values, database)
    interrupt_after = max(0.4, elapsed * 0.45)
    status, elapsed_i, tail_i = _run_upgrade(
        values, database, env_file, timeout=interrupt_after
    )
    interrupted_state = _db_state(values, database)
    report["steps"]["interrupted_upgrade"] = {
        "status": status,
        "seconds": round(elapsed_i, 3),
        "interrupt_after_seconds": round(interrupt_after, 3),
        "state": interrupted_state,
        "output_tail": tail_i,
    }
    if status != "interrupted":
        # 迁移过快导致未能在窗口内中断：不是失败，但需如实记录
        report["steps"]["interrupted_upgrade"]["note"] = "迁移在中断窗口内已完成"

    # 3) 中断后重跑至完成
    status_r, elapsed_r, tail_r = _run_upgrade(values, database, env_file, timeout=None)
    recovered_state = _db_state(values, database)
    report["steps"]["resume_upgrade"] = {
        "status": status_r,
        "seconds": round(elapsed_r, 3),
        "state": recovered_state,
        "output_tail": tail_r,
    }
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    ok = (
        status_r == "ok"
        and recovered_state["revision"] == head
        and set(recovered_state["key_tables_present"]) == set(KEY_TABLES)
    )
    report["status"] = "ok" if ok else "failed"

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
