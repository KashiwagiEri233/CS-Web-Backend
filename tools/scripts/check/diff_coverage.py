#!/usr/bin/env python3
"""PR 级 diff 覆盖率门禁（ER-45）。

读取 pytest-cov 生成的 ``coverage.xml`` + ``git diff`` 新增行，计算新增代码
（``app/**``，与 .coveragerc 的 source 对齐）的行覆盖率，低于阈值则 exit 1——
拦截「PR 新增代码零测试」：全量覆盖率再高，改动行没测也过不了门禁。

用法：
  python tools/scripts/check/diff_coverage.py --base origin/main --threshold 80 \
      --xml build/coverage.xml --src app

退出码：0 通过（或无新增行）；1 覆盖率不足 / 运行错误。
仅标准库（xml.etree / subprocess / argparse），与根仓脚本 scripts/check/check_version_sync.py 同风格。

与前端 `tools/scripts/check/diff-coverage.mjs` 为同一门禁（ER-45）的两端实现（本仓 app/**、前端 src/**），
CLI 参数 `--base/--threshold/--src` 保持一致；调整阈值/报告格式时需两端同步。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PR 级 diff 覆盖率门禁（ER-45）")
    p.add_argument("--base", default="origin/main", help="diff 基线 ref（默认 origin/main）")
    p.add_argument("--threshold", type=float, default=80.0, help="新增行覆盖率阈值 %%")
    p.add_argument("--xml", default="build/coverage.xml", help="coverage.xml 路径")
    p.add_argument("--src", default="app", help="被测源码目录（相对仓库根）")
    return p.parse_args(argv)


def parse_coverage_xml(xml_path: str, src: str) -> dict[str, set[int]]:
    """coverage.xml → {仓库相对路径: 已覆盖行号集合}。

    coverage.py 的 xml 报告 filename 相对 ``source`` 根（本仓为 app/），
    git diff 路径是 ``app/...`` 仓库相对形式——此处统一归一到后者。
    """
    if not Path(xml_path).exists():
        raise SystemExit(f"coverage.xml 未找到：{xml_path}（请先跑 pytest --cov 生成覆盖率）")
    root = ET.parse(xml_path).getroot()
    cwd = str(Path.cwd())
    cov: dict[str, set[int]] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename") or ""
        if not filename:
            continue
        if filename.startswith(cwd + "/"):
            filename = filename[len(cwd) + 1 :]
        elif filename.startswith("/"):
            filename = filename.lstrip("/")
        # 相对 source 根（core/constants.py）→ 仓库相对（app/core/constants.py）
        if not filename.startswith(src + "/"):
            filename = f"{src}/{filename}"
        covered = {
            int(line.get("number"))
            for line in cls.iter("line")
            if int(line.get("hits") or 0) > 0
        }
        cov[filename] = covered
    return cov


_HEADER_RE = re.compile(r"\+(\d+)(?:,(\d+))?")


def get_added_lines(base: str, src: str) -> dict[str, list[int]]:
    """git diff（unified=0）→ {仓库相对路径: 新增行号列表}。"""
    added: dict[str, list[int]] = {}
    try:
        diff = subprocess.run(
            ["git", "diff", "--unified=0", "--no-color", f"{base}...HEAD", "--", f"{src}/**"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"git diff 失败（base={base}）："
            + ((e.stderr or e.stdout or "").strip().splitlines() or [str(e)])[0]
        )
    cur_lines: list[int] | None = None
    line_no = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p == "/dev/null":
                cur_lines = None
                continue
            if p.startswith("b/"):
                p = p[2:]
            cur_lines = []
            added[p] = cur_lines
        elif line.startswith("@@"):
            m = _HEADER_RE.search(line)
            if m:
                line_no = int(m.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            if cur_lines is not None:
                cur_lines.append(line_no)
            line_no += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass  # 删除行：新文件行号不前进
        elif line.startswith(" "):
            line_no += 1  # context 行：新文件行号前进（-U0 下通常无）
    for k in [k for k, v in added.items() if not v]:
        del added[k]
    return added


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])
    cov = parse_coverage_xml(args.xml, args.src)
    added = get_added_lines(args.base, args.src)

    total = 0
    covered = 0
    report: list[tuple[str, int, int, float]] = []
    for file, lines in sorted(added.items()):
        cov_set = cov.get(file)
        hit = len([l for l in lines if cov_set is not None and l in cov_set])
        total += len(lines)
        covered += hit
        pct = (hit / len(lines)) * 100 if lines else 100.0
        report.append((file, len(lines), hit, pct))

    pct_total = (covered / total) * 100 if total else 100.0
    print(
        f"[diff-coverage] base={args.base} src={args.src} "
        f"threshold={args.threshold:g}% xml={args.xml}"
    )
    if total == 0:
        print("[diff-coverage] 无新增代码行（app/**），跳过门禁 → PASS")
        sys.exit(0)
    print(f"[diff-coverage] 新增行覆盖率：{covered}/{total} = {pct_total:.2f}%")
    for file, added_n, hit_n, pct in sorted(report, key=lambda r: -r[1]):
        flag = "✓" if pct >= 100 else "~" if pct >= args.threshold else "✗"
        print(f"  {flag} {file}  新增 {added_n} / 覆盖 {hit_n} ({pct:.2f}%)")
    if pct_total >= args.threshold:
        print(f"[diff-coverage] PASS（{pct_total:.2f}% ≥ {args.threshold:g}%）")
        sys.exit(0)
    print(
        f"[diff-coverage] FAIL：新增代码覆盖率 {pct_total:.2f}% "
        f"低于阈值 {args.threshold:g}%，请为新增代码补测试",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
