#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-platform Laterbill pipeline without shell-pipe encoding loss."""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run harvest → repayment → render safely.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-items", type=int, default=10)
    parser.add_argument("--sessions-root")
    parser.add_argument("--kinds", default="all")
    parser.add_argument("--git", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--anonymize", action="store_true")
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
