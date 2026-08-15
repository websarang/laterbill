#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laterbill / install.py  —  설치기 겸 진단기

    python scripts/install.py            진단만 (아무것도 바꾸지 않음)
    python scripts/install.py --install  스킬 디렉토리에 설치
    python scripts/install.py --install --scope project

There is nothing to pip install — this skill runs on the standard library
alone. What actually goes wrong for a first-time user is duller than a missing
package: Python is too old, the runtime keeps its transcripts somewhere else,
the skills directory does not exist yet, or there is simply no history to bill.
This script checks each of those and says which one it is.

It reports before it writes, and it never touches anything outside the skills
directory it is installing into.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SKILL_NAME = "laterbill"
MIN_PYTHON = (3, 9)
HOME = os.path.expanduser("~")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What gets copied. Public-repo docs and generated evidence stay outside the Skill.
PAYLOAD = ["SKILL.md", "agents", "scripts", "references", "samples", "fixtures"]

# Where each runtime keeps its skills, and where it keeps its transcripts.
TARGETS = {
    "claude-code-user": {
        "label": "Claude Code (개인)",
        "skills": os.path.join(HOME, ".claude", "skills"),
        "marker": os.path.join(HOME, ".claude"),
    },
    "claude-code-project": {
        "label": "Claude Code (이 프로젝트)",
        "skills": os.path.join(os.getcwd(), ".claude", "skills"),
        "marker": os.path.join(os.getcwd(), ".claude"),
    },
    "codex-user": {
        "label": "Codex (개인)",
        "skills": os.path.join(os.environ.get("CODEX_HOME", os.path.join(HOME, ".codex")),
                               "skills"),
        "marker": os.environ.get("CODEX_HOME", os.path.join(HOME, ".codex")),
    },
}
TRANSCRIPTS = [
    ("claude-code", os.path.join(HOME, ".claude", "projects")),
    ("codex", os.path.join(HOME, ".codex", "sessions")),
    ("codex", os.path.join(HOME, ".codex", "archived_sessions")),
]

OK, WARN, BAD = "  OK ", " 주의 ", " 실패 "


def count_transcripts() -> list[tuple[str, str, int]]:
    found = []
    for label, root in TRANSCRIPTS:
        if os.path.isdir(root):
            n = len(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))
            found.append((label, root, n))
    return found


def diagnose() -> bool:
    """Print what is and is not ready. Returns False if the skill cannot run."""
    fatal = False
    print("진단\n")

    version = sys.version_info
    if version >= MIN_PYTHON:
        print(f"{OK} 파이썬 {version.major}.{version.minor}.{version.micro}")
    else:
        need = ".".join(map(str, MIN_PYTHON))
        print(f"{BAD} 파이썬 {version.major}.{version.minor} — {need} 이상이 필요합니다")
        fatal = True

    print(f"{OK} 설치할 패키지 없음 (표준 라이브러리만 사용)")

    scripts_ok = all(
        os.path.isfile(os.path.join(ROOT, "scripts", f))
        for f in ("harvest.py", "render.py", "selftest.py")
    )
    print(f"{OK if scripts_ok else BAD} 스크립트 파일")
    fatal = fatal or not scripts_ok

    found = count_transcripts()
    total = sum(n for _, _, n in found)
    if total:
        for label, root, n in found:
            print(f"{OK} {label} 기록 {n}개 — {root.replace(HOME, '~')}")
    else:
        print(f"{WARN} 읽을 수 있는 대화 기록이 없습니다")
        print("       → 동봉된 예시로 실행하실 수 있습니다:  "
              "python scripts/harvest.py --demo | python scripts/render.py")
        print("       → 기록이 다른 곳에 있다면:  --sessions-root <경로>")

    for key, target in TARGETS.items():
        exists = os.path.isdir(target["marker"])
        installed = os.path.isdir(os.path.join(target["skills"], SKILL_NAME))
        state = "설치됨" if installed else ("설치 가능" if exists else "런타임 없음")
        mark = OK if installed else (OK if exists else WARN)
        print(f"{mark} {target['label']}: {state}  ({target['skills'].replace(HOME, '~')})")

    return not fatal


def install(runtime: str, scope: str, force: bool) -> int:
    if scope == "project" and runtime in ("codex", "all"):
        print(f"{BAD} Codex는 확인된 사용자 Skill 경로에만 설치합니다. "
              "--runtime claude-code 또는 --scope user를 사용하세요.")
        return 1

    keys = (["claude-code-user", "codex-user"] if runtime == "all"
            else (["codex-user"] if runtime == "codex"
                  else ["claude-code-project" if scope == "project"
                        else "claude-code-user"]))
    for key in keys:
        target = TARGETS[key]
        dest = os.path.abspath(os.path.join(target["skills"], SKILL_NAME))
        skills_root = os.path.abspath(target["skills"])
        if os.path.commonpath([dest, skills_root]) != skills_root:
            print(f"{BAD} 안전하지 않은 설치 경로: {dest}")
            return 1

        print(f"\n설치 위치: {dest}")
        if os.path.isdir(dest) and not force:
            print(f"{WARN} 이미 존재합니다. 덮어쓰려면 --force 를 붙이세요.")
            return 1

        os.makedirs(skills_root, exist_ok=True)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)

        copied = []
        for item in PAYLOAD:
            source = os.path.join(ROOT, item)
            if not os.path.exists(source):
                continue
            destination = os.path.join(dest, item)
            if os.path.isdir(source):
                shutil.copytree(source, destination,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(source, destination)
            copied.append(item)
        print(f"{OK} {target['label']} 복사 완료: {', '.join(copied)}")
    print("\n이제 에이전트에게 이렇게 말하면 됩니다:\n")
    print("    하다 만 일 종결반 실행해줘\n")
    if scope == "project":
        print("(프로젝트 스코프로 설치했습니다. 이 폴더에서 연 세션에서만 보입니다.)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Diagnose the environment and optionally install the skill."
    )
    ap.add_argument("--install", action="store_true",
                    help="copy the skill into the skills directory (default: diagnose only)")
    ap.add_argument("--runtime", choices=["all", "claude-code", "codex"], default="all",
                    help="install for both runtimes or choose one (default: all)")
    ap.add_argument("--scope", choices=["user", "project"], default="user",
                    help="user = ~/.claude/skills, project = ./.claude/skills")
    ap.add_argument("--force", action="store_true", help="overwrite an existing installation")
    args = ap.parse_args()

    healthy = diagnose()
    if not args.install:
        print("\n설치하려면:  python scripts/install.py --install")
        return 0 if healthy else 1
    if not healthy:
        print(f"\n{BAD} 위의 실패 항목을 먼저 해결해 주세요. 설치를 중단합니다.")
        return 1
    return install(args.runtime, args.scope, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
