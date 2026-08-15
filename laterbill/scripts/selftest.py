#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laterbill / selftest.py  —  한 줄 자가 검증

    python scripts/selftest.py

README와 SKILL.md가 주장하는 것을 전부 실제로 실행해서 확인한다.
전 항목 PASS면 종료 코드 0, 하나라도 깨지면 1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

sys.path.insert(0, os.path.join(ROOT, "scripts"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def run(args: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY] + args, capture_output=True, text=True, encoding="utf-8",
        cwd=ROOT, input=stdin_text, timeout=120,
    )


# 1 — 데모 파이프라인: 수집 → 발행이 끊기지 않는다
harvested = run(["scripts/harvest.py", "--demo", "--max-items", "6"])
rendered = run(["scripts/render.py"], stdin_text=harvested.stdout)
check(
    "데모 파이프라인이 청구서를 발행한다",
    harvested.returncode == 0 and rendered.returncode == 0
    and "청구 내역" in rendered.stdout and "마지막으로 남긴 말" in rendered.stdout,
)

# 2 — 증거가 없으면 발행을 거부한다 (없는 빚을 지어내지 않음)
empty_h = run(["scripts/harvest.py", "--sessions-root", "fixtures/empty"])
empty_r = run(["scripts/render.py"], stdin_text=empty_h.stdout)
check(
    "증거가 없으면 insufficient_data 로 발행을 거부한다",
    "insufficient_data" in empty_r.stdout and "발행하지 않습니다" in empty_r.stdout,
)

# 3 — 익명화: 수치는 남고 신원은 사라진다
anon = run(["scripts/harvest.py", "--demo", "--anonymize", "--max-items", "6"])
check(
    "익명화가 이름·인용문을 지우고 수치를 남긴다",
    "프로젝트 A" in anon.stdout and "todo-app" not in anon.stdout
    and '"principal_turns"' in anon.stdout,
)

# 4 — 마스킹: 비밀·개인정보가 인용문을 통과하지 못한다
import harvest  # noqa: E402
import repayment  # noqa: E402
import render as bill_render  # noqa: E402

masked = harvest.redact(
    "mail a@b.com key ghp_ABCDEFGH12345678 password=hunter2 "
    "tel 010-1234-5678 path C:\\Users\\secretname\\work"
)
leaks = [t for t in ("a@b.com", "ghp_ABCDEFGH12345678", "hunter2",
                     "010-1234-5678", "secretname") if t in masked]
check("이메일·토큰·비밀번호·전화·홈 경로가 마스킹된다", not leaks, str(leaks))

# 5 — HTML 판이 렌더링된다
html_r = run(["scripts/render.py", "--format", "html"], stdin_text=harvested.stdout)
check("HTML 청구서가 렌더링된다",
      "하다 만 일 종결반" in html_r.stdout and "<style>" in html_r.stdout)

# 6 — 근거 없는 납부 기한을 만들지 않는다 (스키마 불변식)
doc = json.loads(harvested.stdout)
invariant = all(
    (item["due"]["in_days"] is None) == (item["due"]["basis"] in ("no_basis", "dormant"))
    for item in doc["line_items"]
)
check("근거 없는 납부 기한을 만들지 않는다", invariant)

# 7 — 탕감 권고 항목에는 납부 기한이 찍히지 않는다 (자기모순 금지)
consistent = all(
    item["due"]["in_days"] is None
    for item in doc["line_items"] if item["status"] == "write_off_candidate"
)
check("탕감 권고 항목에 납부 기한을 찍지 않는다", consistent)

# 8 — 정지 신호가 실제로 탐지되고, 근거 없는 항목에는 붙지 않는다.
#     후자가 핵심이다: 모든 항목에 라벨이 붙는다면 그건 탐지가 아니라 배정이다.
signal_types = {
    signal["type"]
    for item in doc["line_items"]
    for signal in item.get("stall_signals", [])
}
blank = [item for item in doc["line_items"] if not item.get("stall_signals")]
check(
    "정지 신호를 탐지하되 근거 없는 항목은 비워 둔다",
    len(signal_types) >= 3 and len(blank) >= 1,
    f"탐지된 유형 {sorted(signal_types)} / 신호 없는 항목 {len(blank)}건",
)

# 9 — 정지 신호가 동기를 진단하지 않는다 (심판 금지 규칙의 기계적 검사)
JUDGING_WORDS = ("무서", "두려", "게을", "회피", "포기했", "의지", "실패자", "핑계")
rendered_all = rendered.stdout
verdicts = [w for w in JUDGING_WORDS if w in rendered_all]
check("정지 신호가 동기·성격을 진단하지 않는다", not verdicts, str(verdicts))

# 10 — 익명화가 정지 신호를 통해 프로젝트 이름을 흘리지 않는다.
#      new_project_nearby 는 다른 프로젝트를 지목하므로 여기가 가장 새기 쉽다.
real_names = ("todo-app", "blog-migration", "portfolio-site", "crawler", "thesis-figures")
name_leaks = [n for n in real_names if n in anon.stdout]
check("익명화가 정지 신호로 이름을 흘리지 않는다", not name_leaks, str(name_leaks))

# 11 — README가 앞세우는 한 줄 명령이 셸에서 실제로 돌아간다.
#      PowerShell은 프로세스 사이 파이프에 BOM을 끼워 넣는다. 그 BOM 하나로
#      대표 명령이 죽었던 적이 있어, 회귀하지 않도록 여기서 잡는다.
piped = run(["scripts/render.py"], stdin_text="﻿" + harvested.stdout)
check("BOM이 섞인 파이프 입력도 처리한다",
      piped.returncode == 0 and "청구 내역" in piped.stdout,
      piped.stderr.strip()[:120])

# 12 — 다른 런타임의 타임스탬프 표기를 받아낸다.
#      README가 "5개 필드만 맞으면 어떤 JSONL이든 붙는다"고 약속하므로,
#      오프셋 없는 현지시각 하나로 전 실행이 죽으면 그 약속이 거짓이 된다.
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

stamp_forms = {
    "naive": lambda t: t.isoformat(),
    "zulu": lambda t: t.isoformat() + "Z",
    "offset": lambda t: t.isoformat() + "+09:00",
    "epoch": lambda t: int(t.timestamp()),
}
broken: list[str] = []
for form_name, to_stamp in stamp_forms.items():
    scratch = tempfile.mkdtemp()
    base = datetime.now()
    with open(os.path.join(scratch, "s.jsonl"), "w", encoding="utf-8") as fh:
        for step in range(80):
            when = base - timedelta(days=40 - step * 0.4)
            for role in ("user", "assistant"):
                fh.write(json.dumps({
                    "type": role, "timestamp": to_stamp(when), "sessionId": "s1",
                    "cwd": "/home/u/otherproj", "isSidechain": False,
                    "message": {"role": role, "content": "이 부분 계속 진행해줘 어떻게 할까?"},
                }, ensure_ascii=False) + "\n")
    probe = run(["scripts/harvest.py", "--sessions-root", scratch])
    if probe.returncode != 0 or '"verdict": "ok"' not in probe.stdout:
        broken.append(form_name)
check("다른 런타임의 타임스탬프 표기를 받아낸다", not broken, str(broken))

# 13 — 민감한 사안은 표시되고, 공유용 청구서에서는 그 표시조차 남지 않는다.
flagged = harvest.sensitive_topics("병원 예약 잡는 것도 나중에 해야지")
clean = harvest.sensitive_topics("파서 리팩터링은 나중에 하자")
anon_doc = json.loads(anon.stdout)
anon_flags = [t for item in anon_doc["line_items"] for t in item.get("sensitive_topics", [])]
check(
    "민감한 사안을 표시하고 공유용에서는 그 표시도 지운다",
    flagged == ["health"] and clean == [] and not anon_flags,
    f"flagged={flagged} clean={clean} anon={anon_flags}",
)

# 14 — 망가진 줄 하나가 전체 실행을 죽이지 않는다.
#      이건 사용자의 기록 전부다. 대체로 온전하기만 하면 계산은 성립해야 한다.
scratch = tempfile.mkdtemp()
rows: list[str] = ["{ not json", "", "null", "[]", '{"type":"user"}',
                   '{"type":"user","timestamp":"garbage"}']
base = datetime.now()
for step in range(60):
    when = base - timedelta(days=30 - step * 0.4)
    for role in ("user", "assistant"):
        rows.append(json.dumps({
            "type": role, "timestamp": when.isoformat() + "Z", "sessionId": "s1",
            "cwd": "/home/u/mixedproj", "isSidechain": False,
            "message": {"role": role, "content": "계속 진행해줘 어떻게 할까?"},
        }, ensure_ascii=False))
with open(os.path.join(scratch, "s.jsonl"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(rows) + "\n")
messy = run(["scripts/harvest.py", "--sessions-root", scratch])
check("깨진 줄이 섞인 기록도 완주한다",
      messy.returncode == 0 and '"verdict": "ok"' in messy.stdout,
      messy.stderr.strip()[-100:])

# 15 — HTML 청구서는 인용문을 이스케이프한다. 인용문은 사용자가 쓴 임의의 문자열이고,
#      그 결과물이 브라우저에서 열린다.
inject = json.loads(harvested.stdout)
for entry in inject["line_items"]:
    if entry.get("last_words"):
        entry["last_words"]["text"] = "<script>alert(1)</script>"
escaped = run(["scripts/render.py", "--format", "html"],
              stdin_text=json.dumps(inject, ensure_ascii=False))
check("HTML 청구서에 스크립트가 주입되지 않는다",
      "<script>alert(1)</script>" not in escaped.stdout and "&lt;script&gt;" in escaped.stdout)

# 16 — 로컬 전용 주장을 소스로 확인한다. 문서가 아니라 코드가 근거다.
sources = ""
for script in ("harvest.py", "render.py", "install.py"):
    with open(os.path.join(ROOT, "scripts", script), encoding="utf-8") as fh:
        sources += fh.read()
network = [lib for lib in ("import socket", "urllib", "requests",
                           "http.client", "httpx", "ftplib") if lib in sources]
check("네트워크 라이브러리를 import 하지 않는다", not network, str(network))

# 17 — 윈도우에서 만든 기록을 macOS/Linux 에서 읽어도 프로젝트 이름이 온전하다.
#      기록은 기계 사이를 옮겨 다니고, 동봉 데모 픽스처 자체가 윈도우 경로다.
#      os.path.basename 은 실행 중인 OS 를 따르므로 이 검사가 필요하다.
mixed_paths = [
    (r"C:\demo\todo-app", "todo-app"),
    (r"C:\Users\u\proj\crawler", "crawler"),
    ("/home/u/blog-migration", "blog-migration"),
    ("/Users/u/thesis-figures", "thesis-figures"),
    (r"D:\work\api\\", "api"),
]
wrong = [(raw, harvest.path_label(raw)) for raw, want in mixed_paths
         if harvest.path_label(raw) != want]
check("윈도우·POSIX 경로 모두에서 프로젝트 이름을 뽑아낸다", not wrong, str(wrong))

# 18 — 최신 Codex envelope(session_meta/turn_context/response_item)를 실제로 읽는다.
scratch = tempfile.mkdtemp()
codex_file = os.path.join(scratch, "codex.jsonl")
base = datetime.now() - timedelta(days=12)
rows = [
    {"timestamp": (base - timedelta(days=2)).isoformat() + "Z", "type": "session_meta",
     "payload": {"id": "codex-session-1", "cwd": scratch}},
    {"timestamp": (base - timedelta(days=2)).isoformat() + "Z", "type": "turn_context",
     "payload": {"cwd": scratch, "git_branch": "main"}},
]
for step in range(40):
    when = base + timedelta(minutes=step)
    for role, block_type, text in (
        ("user", "input_text", "배포 전에 테스트가 실패해. 다음 단계를 확인해줘"),
        ("assistant", "output_text", "현재 테스트 상태를 확인하겠습니다."),
    ):
        rows.append({
            "timestamp": when.isoformat() + "Z", "type": "response_item",
            "payload": {"type": "message", "role": role,
                        "content": [{"type": block_type, "text": text}]},
        })
with open(codex_file, "w", encoding="utf-8") as fh:
    fh.write("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
codex_turns, codex_stats = harvest.read_turns([("codex", codex_file)])
check(
    "최신 Codex envelope에서 세션·프로젝트·대화를 읽는다",
    len(codex_turns) == 80
    and {t["session"] for t in codex_turns} == {"codex-session-1"}
    and {t["cwd"] for t in codex_turns} == {scratch},
    f"turns={len(codex_turns)} sessions={set(t['session'] for t in codex_turns)}",
)

# 19 — 런타임별 발견 파일/파싱 턴 통계를 구분한다.
stats = codex_stats["by_runtime"].get("codex", {})
check(
    "런타임별 발견 파일과 파싱 대화 수를 보고한다",
    stats.get("files_discovered") == 1 and stats.get("files_read") == 1
    and stats.get("turns_parsed") == 80,
    str(stats),
)

# 20 — 프로젝트·세션으로 돌아가는 private source_refs를 보존한다.
debts = harvest.build_project_debts(codex_turns, datetime.now().astimezone())
source_ok = bool(debts and debts[0].get("source_refs"))
if source_ok:
    ref = debts[0]["source_refs"][0]
    source_ok = (ref["runtime"] == "codex" and ref["session_id"] == "codex-session-1"
                 and ref["project_path"] == scratch and ref["project_exists"])
check("청구 항목이 프로젝트와 마지막 세션의 source_refs를 보존한다", source_ok)

# 21 — 공유용 장부에서는 경로·세션·원본 식별자를 제거한다.
anon_source_doc = json.loads(anon.stdout)
serialized_anon = json.dumps(anon_source_doc, ensure_ascii=False)
private_refs = [ref for item in anon_source_doc["line_items"]
                for ref in item.get("source_refs", [])]
check(
    "익명화가 프로젝트 경로·세션 ID·private source_refs를 제거한다",
    not private_refs and "session_id" not in serialized_anon
    and "project_path" not in serialized_anon,
)

# 22 — 근거가 충분한 항목에는 실질적으로 다른 상환안 3개를 만든다.
option_item = harvest.finalize({
    "kind": "abandoned_project", "label": "sample", "project": scratch,
    "principal_turns": 80, "first_seen": (base - timedelta(days=2)).isoformat(),
    "last_seen": base.isoformat(), "idle_days": 12, "revisits": 1,
    "revisit_gaps_days": [2.0], "mean_revisit_gap_days": 2.0,
    "runtimes": ["codex"], "sessions": 1, "deadline_signals": [],
    "stall_signals": [{"type": "stalled_before_ship", "detail": "배포 이야기 중 기록이 멈춤"}],
    "last_words": {"ts": base.isoformat(), "text": "배포 전에 테스트가 실패해. 다음 단계를 확인해줘"},
    "source_refs": [{"runtime": "codex", "session_id": "codex-session-1",
                     "project_path": scratch, "project_exists": True,
                     "last_seen": base.isoformat()}],
}, datetime.now().astimezone())
snapshot = repayment.inspect_project(option_item)
options, option_note = repayment.build_options(option_item, snapshot)
option_item["repayment_options"] = options
check(
    "근거에 맞춘 빠른 진전·장애물 해소·완결 우선 3안을 구체적으로 제시한다",
    len(options) == 3 and {o["strategy"] for o in options}
    == {"quick-win", "unblock", "completion"}
    and len({o["first_action"] for o in options}) == 3 and option_note is None
    and "첫 빌드 오류" in options[0]["title"]
    and "유지할 결과" in options[1]["first_action"]
    and "배포 차단 요소" in options[2]["done_when"]
    and all(
        marker in repayment.contextual_option_copy(
            {"last_words": {"text": words}}, {"public_demo": True}
        )["A"][1]
        for words, marker in (
            ("원격에서도 작업하려면?", "GitHub 연결"),
            ("사례글로 만들어줘", "초안과 참고 페이지"),
            ("상태가 sent인데 성공한 거야?", "발송 1건"),
            ("프로젝트에서 claude 실행이 안돼", "Claude 설치 경로"),
            ("영상 자막을 SRT로 만들어줘", "첫 1분"),
        )
    ),
)

# 23 — 정지 유형에 맞는 안을 추천한다.
recommended = [o["option_id"] for o in options if o.get("recommended")]
check("배포 직전 정지에는 완결 우선 C안을 추천한다", recommended == ["C"], str(recommended))

# 24 — 근거가 없거나 프로젝트가 사라지면 3안을 지어내지 않는다.
missing = dict(option_item)
missing["source_refs"] = [{"runtime": "codex", "session_id": "gone",
                           "project_path": os.path.join(scratch, "gone"),
                           "project_exists": False, "last_seen": base.isoformat()}]
missing_options, missing_note = repayment.build_options(missing, repayment.inspect_project(missing))
check(
    "프로젝트가 없으면 위치 복구안만 내고 추가안을 지어내지 않는다",
    len(missing_options) == 1 and "위치 복구" in missing_options[0]["title"]
    and bool(missing_note),
)

# 25 — 선택안만 상세화하고 작업 수·완료 조건·자가개선 루프를 고정한다.
detail = repayment.build_detail(option_item, "C", "repay", snapshot)
improve = detail.get("self_improvement") or {}
check(
    "상환 상세계획은 최대 3개 작업과 자가개선 가드레일을 포함한다",
    detail["selected_option"] == "C" and 1 <= len(detail["tasks"]) <= 3
    and all(t.get("files_or_area") and t.get("command_or_action") and t.get("done_when")
            for t in detail["tasks"])
    and all(improve.get(k) for k in ("observed_pattern", "guardrail", "checkpoint",
                                     "success_signal", "review_after")),
)

# 26 — 분납은 첫 작업 하나와 30분만 허용한다.
installment = repayment.build_detail(option_item, "B", "installment", snapshot)
check("분납은 첫 작업 하나만 30분으로 만든다",
      len(installment["tasks"]) == 1 and installment["timebox"] == 30)

# 27 — 민감 원문은 승인 전 Markdown/HTML 어디에도 나오지 않는다.
sensitive_doc = json.loads(harvested.stdout)
sensitive_item = sensitive_doc["line_items"][0]
sensitive_item["last_words"]["text"] = "민감원문-절대노출금지"
sensitive_item["sensitive_topics"] = ["health"]
sensitive_item["sensitive_approved"] = False
sensitive_item["repayment_options"] = []
sensitive_item["repayment_note"] = "사적인 사안입니다. 사용자 승인 후에만 상환안을 생성합니다."
sensitive_md = run(["scripts/render.py"], stdin_text=json.dumps(sensitive_doc, ensure_ascii=False))
sensitive_html = run(["scripts/render.py", "--format", "html"],
                     stdin_text=json.dumps(sensitive_doc, ensure_ascii=False))
check(
    "민감 원문은 승인 전 Markdown과 HTML에서 기본 숨김 처리된다",
    "민감원문-절대노출금지" not in sensitive_md.stdout
    and "민감원문-절대노출금지" not in sensitive_html.stdout
    and "승인 전 비공개" in sensitive_md.stdout and "승인 전" in sensitive_html.stdout,
)

# 28 — 읽기 전용 재진입 점검은 프로젝트 파일을 바꾸지 않는다.
probe_file = os.path.join(scratch, "README.md")
with open(probe_file, "w", encoding="utf-8") as fh:
    fh.write("demo")
before = (os.path.getmtime(probe_file), open(probe_file, encoding="utf-8").read())
repayment.inspect_project(option_item)
after = (os.path.getmtime(probe_file), open(probe_file, encoding="utf-8").read())
check("상환안 생성을 위한 프로젝트 점검은 파일을 변경하지 않는다", before == after)

# 29 — 출력 문구가 동기·성격을 진단하지 않는다.
repayment_text = json.dumps(options + [detail], ensure_ascii=False)
repayment_verdicts = [w for w in JUDGING_WORDS if w in repayment_text]
check("상환안과 자가개선 계획이 동기·성격을 진단하지 않는다",
      not repayment_verdicts, str(repayment_verdicts))

# 30 — 통합 실행기는 PowerShell 파이프 인코딩에 기대지 않고 한글과 3안을 보존한다.
wrapper = run(["scripts/run.py", "--demo", "--max-items", "1"])
check(
    "통합 실행기가 한글과 A·B·C 상환안을 보존한다",
    wrapper.returncode == 0 and "로그인은 되는데" in wrapper.stdout
    and "| A " in wrapper.stdout and "| B " in wrapper.stdout and "| C " in wrapper.stdout,
    wrapper.stderr.strip()[:120],
)

# 31 — 런타임별 재개 명령을 정확히 만든다.
codex_command = bill_render.resume_command({
    "runtime": "codex", "project_exists": True,
    "project_path": r"C:\work\sample", "session_id": "codex-1",
})
claude_command = bill_render.resume_command({
    "runtime": "claude-code", "project_exists": True,
    "project_path": r"C:\work\sample", "session_id": "claude-1",
})
check(
    "Codex와 Claude Code의 마지막 대화 재개 명령을 만든다",
    codex_command == 'codex resume -C "C:\\work\\sample" "codex-1"'
    and claude_command == 'cd "C:\\work\\sample" && claude --resume "claude-1"',
    f"codex={codex_command} claude={claude_command}",
)

# 32 — 탕감은 실행 작업 없이 결정과 자가개선 확인점만 기록한다.
writeoff_doc = json.loads(harvested.stdout)
writeoff_doc["line_items"] = [option_item]
writeoff_run = run(
    ["scripts/repayment.py", "--item", option_item["item_id"], "--mode", "write-off",
     "--reason", "현재 목표에서 제외"],
    stdin_text=json.dumps(writeoff_doc, ensure_ascii=False),
)
writeoff = json.loads(writeoff_run.stdout)["line_items"][0].get("settlement_record", {})
check(
    "탕감은 실행 작업을 만들지 않고 결정만 기록한다",
    writeoff.get("status") == "write_off" and writeoff.get("tasks") == []
    and writeoff.get("reason") == "현재 목표에서 제외"
    and bool(writeoff.get("self_improvement")),
)

# 33 — 민감 항목 승인은 선택한 item_id 하나에만 적용된다.
approval_doc = json.loads(harvested.stdout)
first = approval_doc["line_items"][0]
second = approval_doc["line_items"][1]
for entry in (first, second):
    entry["sensitive_topics"] = ["health"]
    entry["sensitive_approved"] = False
approval_run = run(
    ["scripts/repayment.py", "--approve-sensitive", first["item_id"]],
    stdin_text=json.dumps(approval_doc, ensure_ascii=False),
)
approved_items = json.loads(approval_run.stdout)["line_items"]
check(
    "민감 항목 승인은 지정한 item_id 하나에만 적용된다",
    approved_items[0]["sensitive_approved"] is True
    and approved_items[1]["sensitive_approved"] is False
    and approved_items[0]["repayment_options"]
    and not approved_items[1]["repayment_options"],
)

# 34 — 기본 호출은 자동 발행하고 수동 모드는 안전한 요약에서 멈춘다.
manual_wrapper = run(["scripts/run.py", "--demo", "--manual", "--max-items", "6"])
check(
    "자동 발행과 수동 발행 대기가 명확히 분리된다",
    "청구 내역" in wrapper.stdout
    and manual_wrapper.returncode == 0
    and "청구서 발행 대기" in manual_wrapper.stdout
    and "청구서는 아직 발행하지 않았습니다" in manual_wrapper.stdout
    and "청구 내역" not in manual_wrapper.stdout
    and "마지막으로 남긴 말" not in manual_wrapper.stdout
    and "todo-app" not in manual_wrapper.stdout,
    manual_wrapper.stderr.strip()[:120],
)

# 35 — 한 번 수집한 같은 장부를 텍스트와 HTML로 함께 발행한다.
dual_output_dir = tempfile.mkdtemp()
dual_html = os.path.join(dual_output_dir, "bill.html")
dual_wrapper = run([
    "scripts/run.py", "--demo", "--max-items", "1",
    "--also-html", dual_html,
])
dual_html_text = (
    open(dual_html, encoding="utf-8").read() if os.path.isfile(dual_html) else ""
)
check(
    "자동 발행이 텍스트를 보여주고 동일 청구서를 HTML로 만든다",
    dual_wrapper.returncode == 0
    and "청구 내역" in dual_wrapper.stdout
    and f"HTML 청구서: {dual_html}" in dual_wrapper.stdout
    and "<style>" in dual_html_text
    and "청구 내역" in dual_html_text
    and "todo-app" in dual_wrapper.stdout
    and "todo-app" in dual_html_text,
    dual_wrapper.stderr.strip()[:120],
)

# ---------------------------------------------------------------------------
failed = [entry for entry in results if not entry[1]]
for name, ok, detail in results:
    line = ("PASS  " if ok else "FAIL  ") + name
    if detail and not ok:
        line += f"  ({detail})"
    print(line)
print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
sys.exit(1 if failed else 0)
