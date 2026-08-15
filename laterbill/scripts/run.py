#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-platform Laterbill pipeline without shell-pipe encoding loss."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable


def invoke(script: str, args: list[str], stdin_text: str | None = None) -> str:
    result = subprocess.run(
        [PYTHON, os.path.join(ROOT, "scripts", script), *args],
        input=stdin_text, capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=ROOT, timeout=180,
    )
    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def manual_preview(ledger_text: str) -> str:
    """Return a privacy-safe issuance preview without rendering the bill."""
    ledger = json.loads(ledger_text.lstrip("\ufeff"))
    scope = ledger.get("scan_scope", {})
    summary = ledger.get("summary", {})
    parser_stats = scope.get("parser_stats", {})
    sensitive = sum(
        bool(item.get("sensitive_topics")) and not item.get("sensitive_approved", False)
        for item in ledger.get("line_items", [])
    )
    runtime_lines = []
    for runtime, stats in sorted(parser_stats.items()):
        runtime_lines.append(
            f"- {runtime}: 파일 {stats.get('files_read', 0)}/"
            f"{stats.get('files_discovered', 0)}개 · 대화 {stats.get('turns_parsed', 0):,}턴"
        )
    runtimes = "\n".join(runtime_lines) or "- 수집된 런타임 없음"
    return (
        "# 하다 만 일 종결반 — 청구서 발행 대기\n\n"
        "> 읽기 전용 수집은 완료했지만 청구서는 아직 발행하지 않았습니다.\n\n"
        f"- 발행 가능 항목: **{summary.get('line_items', 0)}건**\n"
        f"- 조사한 대화: **{scope.get('turns_scanned', 0):,}턴**\n"
        f"- 민감 승인 대기: **{sensitive}건**\n"
        f"- 외부 전송: **{scope.get('network_calls', 0)}건**\n\n"
        "## 런타임별 수집\n\n"
        f"{runtimes}\n\n"
        "전체 청구서를 보려면 **`청구서 발행`**이라고 입력하세요. "
        "취소하려면 **`발행 취소`**라고 입력하세요.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run harvest → repayment → render safely.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-items", type=int, default=10)
    parser.add_argument("--sessions-root")
    parser.add_argument("--kinds", default="all")
    parser.add_argument("--git", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--anonymize", action="store_true")
    parser.add_argument(
        "--manual", action="store_true",
        help="collect records and show a privacy-safe preview; do not issue the bill",
    )
    parser.add_argument("--format", choices=["md", "html"], default="md")
    parser.add_argument("-o", "--output", default="-")
    args = parser.parse_args()

    harvest_args = ["--days", str(args.days), "--max-items", str(args.max_items),
                    "--kinds", args.kinds]
    if args.sessions_root:
        harvest_args += ["--sessions-root", args.sessions_root]
    if args.git:
        harvest_args.append("--git")
    if args.demo:
        harvest_args.append("--demo")
    if args.anonymize:
        harvest_args.append("--anonymize")

    ledger = invoke("harvest.py", harvest_args)
    if args.manual:
        sys.stdout.write(manual_preview(ledger))
        return 0

    planned = invoke("repayment.py", [], ledger)
    render_args = ["--format", args.format]
    if args.output != "-":
        render_args += ["--output", args.output]
    bill = invoke("render.py", render_args, planned)
    if args.output == "-":
        sys.stdout.write(bill)
    elif bill:
        sys.stderr.write(bill)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
