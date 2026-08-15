#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laterbill / harvest.py  —  「하다 만 일 종결반」 수확기

Read-only harvester for unpaid intentions.

Most retrospective tools summarise what you DID. This one audits what you
DIDN'T — the work you invested in and then walked away from. That evidence is
already sitting on the machine: transcripts remember every project you opened,
how many turns you poured into it, and the exact sentence you were saying when
you left.

Three kinds of debt are collected:

  1. abandoned_project — you invested N turns, then went silent for D days.
  2. dangling_ask      — a session's final message was a request that never
                         got closed out.
  3. verbal_promise    — you literally said "나중에 할게" / "TODO" / "later".

Interest is not a metaphor: every time you re-entered a project and left it
again, the context had to be rebuilt from scratch. Those re-entries are
counted and billed.

Each abandoned_project debt may also carry stall_signals — evidence-gated
notes on WHERE the trail goes cold. Never a motive ("you were afraid to
ship"), only a situation ("the last few messages were about deploying, then
nothing"): a mind is not in the record, a timestamp is. No forced label
either — a debt with no evidence gets zero signals, the same honesty rule
that governs the due date.

Guarantees (see references/safety.md):
  * READ-ONLY   — never writes, moves, or deletes anything it scans.
  * LOCAL-ONLY  — makes zero network calls.
  * REDACTING   — secrets, emails, phone numbers, home paths are masked.
  * HONEST      — emits `insufficient_data` rather than inventing a debt.

Output: one JSON document on stdout, for the agent to adjudicate and render.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA_VERSION = "3.0"

# A gap this long between turns means you left and came back — a re-entry.
REVISIT_GAP_DAYS = 1.0
# Below this, a project was a passing glance, not an investment worth billing.
MIN_PRINCIPAL_TURNS = 12
# Silence beyond this is not procrastination any more; it is a dead project.
WRITE_OFF_DAYS = 60


# --------------------------------------------------------------------------
# 1. Verbal deferral lexicon — "나중에 할게" 의 여러 얼굴
# --------------------------------------------------------------------------
DEFERRAL_PATTERNS: list[tuple[str, str, float]] = [
    (r"나중에\s*(?:하|해|보|정리|고치|만들|추가|볼|할|알려)", "ko.later", 1.0),
    (r"다음에\s*(?:하|해|보|정리|고치|만들|추가|할|알려)", "ko.next_time", 1.0),
    (r"이따(?:가)?\s*(?:하|해|보)", "ko.in_a_bit", 0.7),
    (r"추후\s*(?:에)?\s*(?:하|해|보|검토|반영|보완|개선)", "ko.afterwards", 1.0),
    (r"조만간", "ko.soon", 0.6),
    (r"언젠가", "ko.someday", 0.8),
    (r"일단\s*(?:넘어가|두|놔두|보류|스킵|건너뛰)", "ko.skip_for_now", 1.0),
    (r"미뤄(?:두|놓|둘)?", "ko.postpone", 1.0),
    (r"뒤로\s*미루", "ko.postpone", 1.0),
    (r"해\s*볼게(?:요)?", "ko.will_try", 0.8),
    (r"해\s*야\s*(?:지|겠다|겠네|겠어)", "ko.should_do", 0.8),
    (r"하려고\s*(?:해|한다|합니다|했)", "ko.intend", 0.7),
    (r"할\s*예정", "ko.planned", 0.8),
    (r"잊지\s*(?:마|말)", "ko.dont_forget", 0.7),
    (r"까먹(?:지\s*않게|기\s*전에)", "ko.before_i_forget", 0.7),
    (r"기억해\s*(?:둬|놔|두)", "ko.remember_this", 0.7),
    (r"(?:메모|적어)\s*(?:해\s*)?(?:둬|놔)", "ko.note_down", 0.6),
    (r"리마인드|\bremind\b", "ko.remind", 0.8),
    (r"\bTODO\b", "en.todo", 1.0),
    (r"\bFIXME\b", "en.fixme", 1.0),
    (r"\bfor now\b", "en.for_now", 0.8),
    (r"\bnext time\b", "en.next_time", 0.8),
    (r"\beventually\b", "en.eventually", 0.8),
    (r"\bcome back to (?:this|it|that)\b", "en.come_back", 1.0),
    (r"\brevisit\b", "en.revisit", 0.9),
    (r"\bdefer(?:red|ring)?\b", "en.defer", 0.9),
    (r"\bpunt(?:ed|ing)?\b", "en.punt", 0.9),
    (r"\bI'?ll (?:do|fix|add|handle|clean|write|check)\b", "en.will_do", 0.9),
    (r"\bskip (?:this|that|it) for now\b", "en.skip_for_now", 1.0),
]

# The marker used as a category name is not a promise:
#   "후보 또는 보류로 분류해줘"  → an instruction about labels
#   "나중에 알려줘"              → an actual deferral
LABEL_USAGE = re.compile(
    r"^\s*(?:로|으로|라고|이라고|라는|이라는|항목|상태|처리|분류|태그|컬럼|필드)"
)
NOISE_LINE = re.compile(r"^\s*(?:```|<|\{|\}|/\*|\"[^\"]*\"\s*:)")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?。？！])\s+")
MIN_SENTENCE_LEN, MAX_SENTENCE_LEN = 6, 300


# --------------------------------------------------------------------------
# 2. Due-date signals — 납부 기한은 추측이 아니라 인용에서 나온다
# --------------------------------------------------------------------------
DEADLINE_PATTERNS: list[tuple[str, str]] = [
    (r"오늘\s*(?:까지|안에)", "today"),
    (r"내일\s*(?:까지)?", "tomorrow"),
    (r"모레", "in_2_days"),
    (r"이번\s*주\s*(?:까지|안에|중)?", "this_week"),
    (r"다음\s*주\s*(?:까지|안에|중)?", "next_week"),
    (r"이번\s*달\s*(?:까지|안에|말)?", "this_month"),
    (r"다음\s*달", "next_month"),
    (r"마감", "deadline_word"),
    (r"발표\s*(?:일|까지)", "presentation"),
    (r"출시|릴리스|릴리즈|배포\s*(?:일|예정)", "release"),
    (r"\bdeadline\b", "deadline_word"),
    (r"\bby (?:today|tomorrow|monday|friday|next week|end of week|EOD|EOW)\b", "en_deadline"),
]
DEADLINE_RES = [(re.compile(p, re.IGNORECASE), lab) for p, lab in DEADLINE_PATTERNS]
DUE_HORIZON_DAYS = {
    "today": 0, "tomorrow": 1, "in_2_days": 2, "this_week": 5, "next_week": 12,
    "this_month": 20, "next_month": 45, "deadline_word": 14, "en_deadline": 7,
    "presentation": 14, "release": 21,
}

# 청구서에 찍히는 것은 사람이 읽는 말이어야 한다. `this_week` 같은 내부 라벨이
# 그대로 나가면 그건 장부가 아니라 로그다.
DEADLINE_KO = {
    "today": "오늘까지", "tomorrow": "내일까지", "in_2_days": "모레까지",
    "this_week": "이번 주까지", "next_week": "다음 주까지",
    "this_month": "이번 달까지", "next_month": "다음 달", "deadline_word": "마감 언급",
    "en_deadline": "마감 언급", "presentation": "발표 일정", "release": "출시·배포 일정",
}


# --------------------------------------------------------------------------
# 3. Redaction — 개인정보/비밀의 경계
# --------------------------------------------------------------------------
REDACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>"),
    (re.compile(r"\b(?:sk|pk|ghp|gho|ghs|xoxb|xoxp)[-_][A-Za-z0-9_-]{8,}"), "<token>"),
    (re.compile(r"(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+", re.I), "<secret>"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "<hash>"),
    (re.compile(r"\b\d{6}-[1-4]\d{6}\b"), "<id-number>"),
    (re.compile(r"\b\d{2,3}-\d{3,4}-\d{4}\b"), "<phone>"),
    (re.compile(r"[A-Za-z]:\\Users\\[^\\/\s\"']+"), "<home>"),
    (re.compile(r"/(?:home|Users)/[^/\s\"']+"), "<home>"),
    (re.compile(r"https?://\S+"), "<url>"),
]


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# Some unfinished things were right to leave unfinished. SKILL.md promises the
# agent will ask before putting these on a bill — but it can only keep that
# promise if something marks them, so the marking happens here.
#
# This flags, it never removes: deciding is the user's, and silently dropping a
# real debt would be its own kind of dishonesty.
SENSITIVE_TOPICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"병원|진료|수술|진단|처방|치료|검진|아프|통증|우울|불안|상담|약\s*먹"), "health"),
    (re.compile(r"장례|부고|이혼|이별|가족\s*문제|부모님|아버지|어머니|배우자|아이\s*문제"), "family"),
    (re.compile(r"대출|빚|이자율|파산|연체료|월세|보증금|세금|해고|퇴사|사직|이직|연봉"), "money_work"),
]


def sensitive_topics(text: str) -> list[str]:
    return sorted({label for pattern, label in SENSITIVE_TOPICS if pattern.search(text)})


# --------------------------------------------------------------------------
# 4. Reading the trail
# --------------------------------------------------------------------------

def parse_ts(value) -> datetime | None:
    """
    Accept the timestamp shapes real runtimes actually write.

    Every comparison downstream is against an aware `now`, so a naive value has
    to be given a zone here or the whole run dies with "can't subtract
    offset-naive and offset-aware datetimes". A runtime that writes local time
    with no offset is the most likely thing someone plugs in next, and the
    README invites exactly that — so it must not be the one input that crashes.
    UTC is the assumption; at day resolution a few hours of skew changes
    nothing that this bill reports.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:  # epoch seconds, and epoch milliseconds for the runtimes that use them
            seconds = value / 1000.0 if value > 1e11 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None
    # Epoch written as a string. Bounded to 10–13 digits so a bare "20260801"
    # is not silently read as a second count.
    if value.isdigit() and 10 <= len(value) <= 13:
        return parse_ts(int(value))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def path_label(cwd: str) -> str:
    """
    Last path segment, whichever platform wrote the path and whichever one is
    reading it.

    `os.path.basename` follows the *running* OS. On macOS and Linux a backslash
    is an ordinary character, so `basename("C:\\demo\\todo-app")` hands back the
    whole string — and the bundled demo fixture is full of Windows paths. A
    reviewer on a Mac would have seen every project named `C:\\demo\\todo-app`.
    Transcripts travel between machines; the split has to be explicit.
    """
    if not cwd:
        return ""
    return cwd.replace("\\", "/").rstrip("/").rpartition("/")[2]


def flatten_content(content) -> str:
    """A turn is either a plain string or a list of typed blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in ("text", "input_text", "output_text"):
            out.append(block.get("text", ""))
    return "\n".join(out)


def discover_session_files(explicit_root: str | None, demo: bool) -> list[tuple[str, str]]:
    """Return (runtime, path) for every transcript we are allowed to read."""
    if demo:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
        return [("demo", p) for p in sorted(glob.glob(os.path.join(base, "*.jsonl")))]

    if explicit_root:
        roots = [("custom", explicit_root)]
    else:
        home = os.path.expanduser("~")
        roots = [
            ("claude-code", os.path.join(home, ".claude", "projects")),
            ("codex", os.path.join(home, ".codex", "sessions")),
            ("codex", os.path.join(home, ".codex", "archived_sessions")),
        ]

    found: list[tuple[str, str]] = []
    for label, root in roots:
        if os.path.isdir(root):
            for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
                found.append((label, path))
    return found


def read_turns(files: list[tuple[str, str]]) -> tuple[list[dict], dict]:
    """Stream Claude Code and modern Codex transcripts into normalized turns."""
    turns: list[dict] = []
    by_runtime: dict[str, dict[str, int]] = defaultdict(
        lambda: {"files_discovered": 0, "files_read": 0, "turns_parsed": 0,
                 "records_skipped": 0}
    )
    for runtime, _ in files:
        by_runtime[runtime]["files_discovered"] += 1

    for runtime, path in files:
        try:
            handle = open(path, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        by_runtime[runtime]["files_read"] += 1
        session_id = os.path.basename(path)
        current_cwd = ""
        current_branch = ""
        with handle as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (ValueError, TypeError):
                    continue
                # A line can be valid JSON and still not be a record: `null`,
                # `[]`, a bare string. One of those must not end the run — this
                # is someone's whole history, and it only has to be mostly well
                # formed for the arithmetic to hold.
                if not isinstance(rec, dict):
                    by_runtime[runtime]["records_skipped"] += 1
                    continue

                record_type = rec.get("type")
                payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}

                # Codex stores session/project state in envelope records. Keep
                # that state for later response_item records in the same file.
                if record_type == "session_meta":
                    session_id = (payload.get("id") or payload.get("session_id")
                                  or session_id)
                    current_cwd = payload.get("cwd") or current_cwd
                    current_branch = payload.get("git_branch") or current_branch
                    continue
                if record_type == "turn_context":
                    current_cwd = payload.get("cwd") or current_cwd
                    current_branch = (payload.get("git_branch") or payload.get("branch")
                                      or current_branch)
                    continue

                role = ""
                content = None
                turn_runtime = runtime
                turn_session = session_id
                turn_cwd = current_cwd
                turn_branch = current_branch

                if record_type == "response_item":
                    if payload.get("type") != "message":
                        continue
                    role = payload.get("role", "")
                    content = payload.get("content")
                    turn_runtime = "codex" if runtime == "custom" else runtime
                elif record_type in ("user", "assistant") and not rec.get("isSidechain"):
                    message = rec.get("message")
                    if not isinstance(message, dict):
                        by_runtime[runtime]["records_skipped"] += 1
                        continue
                    role = record_type
                    content = message.get("content")
                    turn_runtime = "claude-code" if runtime == "custom" else runtime
                    turn_session = rec.get("sessionId") or session_id
                    turn_cwd = rec.get("cwd") or current_cwd
                    turn_branch = rec.get("gitBranch") or current_branch
                else:
                    continue

                if role not in ("user", "assistant"):
                    continue
                ts = parse_ts(rec.get("timestamp") or payload.get("timestamp"))
                text = flatten_content(content)
                if ts is None or not text.strip():
                    by_runtime[runtime]["records_skipped"] += 1
                    continue
                turns.append({
                    "runtime": turn_runtime,
                    "role": role,
                    "ts": ts,
                    "text": text,
                    "session": turn_session,
                    "cwd": turn_cwd or "",
                    "branch": turn_branch or "",
                })
                by_runtime[turn_runtime]["turns_parsed"] += 1
    turns.sort(key=lambda t: t["ts"])
    return turns, {"by_runtime": {k: dict(v) for k, v in sorted(by_runtime.items())}}


def stable_item_id(kind: str, project: str, sessions: list[str]) -> str:
    raw = "|".join((kind, project, *sorted(sessions)))
    return "lb_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


def build_source_refs(project_turns: list[dict], project_path: str) -> list[dict]:
    """Preserve private return-to-source coordinates; anonymize() removes them."""
    latest: dict[tuple[str, str], dict] = {}
    for turn in project_turns:
        key = (turn["runtime"], turn["session"])
        known = latest.get(key)
        if known is None or turn["ts"] > known["ts"]:
            latest[key] = turn
    return [
        {
            "runtime": runtime,
            "session_id": session,
            "project_path": project_path,
            "project_exists": bool(project_path and os.path.isdir(project_path)),
            "last_seen": turn["ts"].isoformat(),
        }
        for (runtime, session), turn in sorted(
            latest.items(), key=lambda entry: entry[1]["ts"], reverse=True
        )
    ]


# --------------------------------------------------------------------------
# 4b. Stall signals — 정지 신호 (원인 진단이 아니라 상황 기록)
# --------------------------------------------------------------------------
# 신호 이름은 전부 상황 서술이다. "배포가 무서워서" 같은 이름은 동기를 진단하고,
# 그건 이 스킬의 "심판하지 않는다" 원칙과 정면으로 충돌한다. 기록에 있는 것은
# 어디까지 갔고 무슨 이야기 중에 끊겼는지뿐이므로, 거기까지만 말한다:
# "왜 안 했나"가 아니라 "어디서 멈췄나".
#
# 규칙은 납부 기한과 같다 — 증거가 없으면 신호를 만들지 않는다. 강제로 하나를
# 고르지 않고, 있는 만큼만(0~여러 개) 붙인다.

# 이 프로젝트가 멈춘 직후 다른 프로젝트가 시작됐는가.
#
# 제작자의 실제 기록(18개 프로젝트)으로 창 크기를 재봤다: 7일이면 10건 중 7건,
# 3일이면 5건이 걸렸다. 여러 프로젝트를 병행하는 사람에게는 "그 무렵 뭔가 시작됐다"가
# 거의 항상 참이다 — 창을 넓게 잡으면 신호가 아니라 배경 소음이 된다. 그래서 창을
# 좁히고, 이름도 인과가 아니라 관측 그대로 붙였다: 넘어간 것을 본 게 아니라
# 시간이 붙어 있는 것을 봤다.
SWITCH_WINDOW_DAYS = 3
# 잠깐 열어본 폴더는 "그쪽으로 주의가 갔다"의 증거가 못 된다.
SWITCH_MIN_TURNS = 60
REWRITE_MIN_HITS = 3            # "처음부터 다시" 류 표현이 이만큼 나오면 신호로 본다
SCOPE_CREEP_MIN_FILES = 15      # --git 병용 시: 미커밋 파일 이 이상
SCOPE_CREEP_MIN_TURNS = 150     # --git 병용 시: 턴 수 이 이상 (둘 다 만족해야 신호)

BLOCKER_WORDS = re.compile(
    r"로그인|인증|OAuth|회원가입|비밀번호|권한\s*설정|토큰\s*발급|"
    r"결제|카드\s*등록|정기결제|구독\s*결제|과금|"
    r"\bauth\b|\blogin\b|\bsign[\s-]?up\b|\bpayment\b|\bcheckout\b|\bstripe\b",
    re.IGNORECASE,
)
SHIP_WORDS = re.compile(
    r"배포|게시|출시|런칭|공개(?:하|해|할)|오픈(?:하|해|할)|"
    r"\bdeploy\b|\brelease\b|\bship\b|\blaunch\b|\bpublish\b|\bgo[\s-]?live\b",
    re.IGNORECASE,
)
RESOLVED_WORDS = re.compile(
    r"완료|됐다|됐어|됐네|성공|해결|끝났|끝냈|마쳤|잘\s*(?:됐|되네|돼)|"
    r"\bdone\b|\bfixed\b|\bresolved\b|\bsucceeded\b|\bworks\s*now\b",
    re.IGNORECASE,
)
REWRITE_WORDS = re.compile(
    r"처음부터\s*다시|새로\s*(?:짜|만들|작성)|갈아\s*엎|전면\s*재작성|리팩터링|리팩토링|"
    r"\brewrite\b|\bfrom\s*scratch\b|\brefactor\b|\bstart\s*over\b",
    re.IGNORECASE,
)


def detect_stall_signals(
    label: str,
    project_turns: list[dict],
    gaps: list[float],
    last_seen: datetime,
    other_project_starts: dict[str, tuple[datetime, int]],
) -> list[dict]:
    """
    Evidence only, never a verdict. Each entry names where the trail goes
    cold, not why — "마지막 대화가 배포 이야기였다" (fact), never "배포가
    무서워서 멈췄다" (motive, unverifiable, and exactly the judgment
    SKILL.md rules out).
    """
    signals: list[dict] = []
    user_turns = [t for t in project_turns if t["role"] == "user"]
    tail_text = " ".join(t["text"] for t in user_turns[-6:])

    # 1) 다른 프로젝트로 넘어감 — 시간 비교만 한다. 키워드 추측이 없어 확신도가 가장 높다.
    #    단, 새 프로젝트가 실제로 자리를 잡았을 때만 (SWITCH_MIN_TURNS). 잠깐 열어본
    #    폴더는 "넘어갔다"의 증거가 못 된다.
    switched_to = sorted(
        (
            (turn_count, other)
            for other, (started, turn_count) in other_project_starts.items()
            if other != label
            and turn_count >= SWITCH_MIN_TURNS
            and 0 <= (started - last_seen).total_seconds() / 86400.0 <= SWITCH_WINDOW_DAYS
        ),
        reverse=True,
    )
    if switched_to:
        # `ref` keeps the other project's name as data rather than baking it into
        # prose — anonymize() has to be able to swap it for an alias, and a name
        # buried inside a sentence would leak straight through a shared bill.
        turn_count, name = switched_to[0]
        signals.append({
            # 관측한 것은 시간의 인접성뿐이다. "넘어갔다"는 그 위에 얹은 해석이므로
            # 장부는 거기까지 말하지 않는다.
            "type": "new_project_nearby",
            "ref": name,
            "detail": (f"멈춘 지 {SWITCH_WINDOW_DAYS}일 안에 `{name}` 프로젝트가 "
                       f"새로 시작되어 {turn_count}턴이 들어갔음"),
            "confidence": "medium",
        })

    # 2) 재진입 간격이 점점 벌어짐 — 이미 계산된 gaps의 추세만 본다 (신규 채굴 없음).
    if len(gaps) >= 3:
        mid = len(gaps) // 2
        first_avg = sum(gaps[:mid]) / mid
        second_avg = sum(gaps[mid:]) / (len(gaps) - mid)
        if second_avg > first_avg * 1.3 and gaps[-1] == max(gaps):
            signals.append({
                "type": "escalating_silence",
                "detail": f"재진입 간격이 평균 {first_avg:.1f}일 → {second_avg:.1f}일로 벌어지는 추세",
                "confidence": "medium",
            })

    # 3) 인증/결제 근처에서 정지 — 마지막 대화에 언급만 있고 해결 신호가 없을 때만.
    if BLOCKER_WORDS.search(tail_text) and not RESOLVED_WORDS.search(tail_text):
        signals.append({
            "type": "stalled_at_blocker",
            "detail": "마지막 대화들에 인증·결제 관련 언급이 있고, 그 뒤 해결됐다는 신호가 없음",
            "confidence": "medium",
        })

    # 4) 배포/게시 직전 정지 — 위와 동일한 논리.
    if SHIP_WORDS.search(tail_text) and not RESOLVED_WORDS.search(tail_text):
        signals.append({
            "type": "stalled_before_ship",
            "detail": "마지막 대화들에 배포·게시 관련 언급이 있고, 그 뒤 완료됐다는 신호가 없음",
            "confidence": "medium",
        })

    # 5) 여러 번 처음부터 다시 시작함 — 프로젝트 전체 발화에서 빈도를 센다.
    rewrite_hits = sum(1 for t in user_turns if REWRITE_WORDS.search(t["text"]))
    if rewrite_hits >= REWRITE_MIN_HITS:
        signals.append({
            "type": "repeated_rewrite",
            "detail": f"\"처음부터 다시\", \"리팩터링\" 류의 표현이 {rewrite_hits}번 등장",
            "confidence": "high" if rewrite_hits >= 5 else "medium",
        })

    return signals


# --------------------------------------------------------------------------
# 5. Debt #1 — abandoned projects
# --------------------------------------------------------------------------

def count_revisits(timestamps: list[datetime]) -> tuple[int, list[float]]:
    """A re-entry is a turn that follows more than a day of silence."""
    revisits, gaps = 0, []
    for earlier, later in zip(timestamps, timestamps[1:]):
        gap = (later - earlier).total_seconds() / 86400.0
        if gap >= REVISIT_GAP_DAYS:
            revisits += 1
            gaps.append(round(gap, 1))
    return revisits, gaps


# Machinery talking to itself, not the human leaving a thought behind.
MACHINE_TEXT = re.compile(
    r"^\s*(?:<(?:task-notification|local-command|command-|system-reminder|task-|tool-)"
    r"|\[Request interrupted|\{|\[\s*\{|```)"
)

# "정리해줘 / 저장해줘 / 수고했어" — closing the session, not opening a debt.
CLOSING_REMARK = re.compile(
    r"(?:진행\s*상황.*(?:저장|정리)|지금까지.*(?:저장|정리|기록)|"
    r"저장해\s*줘|정리해\s*줘|커밋해\s*줘|푸시해\s*줘|수고|고마워|고맙|땡큐|"
    r"\bcommit\b|\bpush\b|\bsave (?:it|this|progress)\b|\bthanks\b|\bthank you\b)"
)

# An unfinished question keeps its hooks in you.
OPEN_QUESTION = re.compile(
    r"(?:\?|은\?|는\?|어떻게|어떡|왜\s|뭐야|뭔가요|무엇|어디|언제|얼마|"
    r"할까|일까|인가|나요|가능해|가능한가|해야\s*(?:해|하나|할까)|"
    r"\bhow\b|\bwhy\b|\bwhat\b|\bshould i\b|\bcan (?:i|we|you)\b)",
    re.IGNORECASE,
)

# Throwaway probes ("1+1은 몇이야?") are not investments.
# No \b here: Korean particles are word characters, so "1+1은" has no boundary.
TRIVIAL_PROBE = re.compile(
    r"^\s*(?:\d+\s*[+\-*/]\s*\d+|test|테스트|ping|hi\b|hello|안녕|ok\b|넵|응\b)", re.I
)

# A working directory that is not a project.
GENERIC_DIRS = {
    "downloads", "desktop", "documents", "tmp", "temp", "users", "user",
    "home", "onedrive", "pictures", "videos", "music", "appdata", "",
}


def is_meaningful_ask(text: str) -> bool:
    """Was the parting message an actual request, or just housekeeping?"""
    stripped = " ".join(text.split())
    if not (12 <= len(stripped) <= 600):
        return False
    if MACHINE_TEXT.match(stripped) or TRIVIAL_PROBE.match(stripped):
        return False
    if re.match(r"^/\w[\w:-]*\s*$", stripped):  # a bare slash command
        return False
    return True


def score_last_words(text: str) -> float:
    """
    Rank candidate parting messages. The one worth quoting is the request that
    was still open when you walked away — not the housekeeping that followed it.
    """
    stripped = " ".join(text.split())
    score = 1.0
    if OPEN_QUESTION.search(stripped):
        score += 2.5
    if any(re.search(p, stripped, re.I) for p, _, _ in DEFERRAL_PATTERNS):
        score += 2.0
    if CLOSING_REMARK.search(stripped):
        score -= 4.0
    if len(stripped) < 25:
        score -= 1.0
    return score


def pick_last_words(project_turns: list[dict], lookback: int = 20) -> dict | None:
    """
    Choose the most load-bearing thing the user said before disappearing.

    "저장해줘" is how a session ends; it is not what was left unfinished. So an
    open request always outranks a closing remark, no matter which came last.
    """
    candidates = [
        turn for turn in project_turns
        if turn["role"] == "user" and is_meaningful_ask(turn["text"])
    ][-lookback:]
    if not candidates:
        return None

    open_asks = [t for t in candidates if not CLOSING_REMARK.search(t["text"])]
    pool = open_asks or candidates
    # Later utterances break ties, so the freshest genuine ask wins.
    return max(
        enumerate(pool),
        key=lambda pair: (score_last_words(pair[1]["text"]), pair[0]),
    )[1]


def build_project_debts(turns: list[dict], now: datetime) -> list[dict]:
    by_project: dict[str, list[dict]] = defaultdict(list)
    for turn in turns:
        if turn["cwd"]:
            by_project[turn["cwd"]].append(turn)

    # new_project_nearby 신호를 계산하려면 청구 대상이 아닌(너무 작거나 아직 따끈한)
    # 프로젝트의 시작 시점도 필요하다 — MIN_PRINCIPAL_TURNS/idle_days 필터 이전의
    # 전체 맵. "당신이 새로 옮겨간 곳"은 아직 청구서에 오르지 않았을 수도 있다.
    project_starts: dict[str, tuple[datetime, int]] = {}
    for cwd, pturns in by_project.items():
        label = path_label(cwd)
        if label.lower() in GENERIC_DIRS or not pturns:
            continue
        first = min(t["ts"] for t in pturns)
        known_first, known_turns = project_starts.get(label, (first, 0))
        project_starts[label] = (min(first, known_first), known_turns + len(pturns))

    debts: list[dict] = []
    for cwd, project_turns in by_project.items():
        if len(project_turns) < MIN_PRINCIPAL_TURNS:
            continue
        label = path_label(cwd)
        if label.lower() in GENERIC_DIRS:
            continue  # a download folder is not a project you abandoned

        timestamps = [t["ts"] for t in project_turns]
        idle_days = (now - timestamps[-1]).days
        if idle_days < 3:
            continue  # still warm; not a debt

        revisits, gaps = count_revisits(timestamps)
        last_words = pick_last_words(project_turns)

        deadline_labels: list[str] = []
        if last_words:
            deadline_labels = find_deadline_signals(last_words["text"])

        other_starts = {k: v for k, v in project_starts.items() if k != label}
        stall_signals = detect_stall_signals(
            label, project_turns, gaps, timestamps[-1], other_starts
        )

        debts.append({
            "kind": "abandoned_project",
            "label": label or cwd,
            "project": redact(cwd),
            "principal_turns": len(project_turns),
            "first_seen": timestamps[0].isoformat(),
            "last_seen": timestamps[-1].isoformat(),
            "idle_days": idle_days,
            "revisits": revisits,
            "revisit_gaps_days": gaps[-5:],
            "mean_revisit_gap_days": round(sum(gaps) / len(gaps), 1) if gaps else None,
            "runtimes": sorted({t["runtime"] for t in project_turns}),
            "sessions": len({t["session"] for t in project_turns}),
            "source_refs": build_source_refs(project_turns, cwd),
            "deadline_signals": deadline_labels,
            "stall_signals": stall_signals,
            "last_words": {
                "ts": last_words["ts"].isoformat(),
                "text": redact(" ".join(last_words["text"].split()))[:400],
            } if last_words else None,
        })
    return debts


# --------------------------------------------------------------------------
# 6. Debt #2 — dangling asks (세션이 질문 위에서 끊긴 경우)
# --------------------------------------------------------------------------

def build_dangling_asks(turns: list[dict], now: datetime, project_labels: set[str]) -> list[dict]:
    by_session: dict[str, list[dict]] = defaultdict(list)
    for turn in turns:
        by_session[turn["session"]].append(turn)

    debts: list[dict] = []
    for session, session_turns in by_session.items():
        if len(session_turns) < 6:
            continue
        idle_days = (now - session_turns[-1]["ts"]).days
        if idle_days < 3:
            continue

        # The parting request, and whether the agent ever answered it.
        last_user_index = next(
            (i for i in range(len(session_turns) - 1, -1, -1)
             if session_turns[i]["role"] == "user"
             and is_meaningful_ask(session_turns[i]["text"])),
            None,
        )
        if last_user_index is None:
            continue
        replies_after = sum(
            1 for t in session_turns[last_user_index + 1:] if t["role"] == "assistant"
        )
        if replies_after >= 2:
            continue  # the ask was answered; nothing outstanding

        ask = session_turns[last_user_index]
        label = path_label(ask["cwd"] or "") or "(unknown)"
        if label in project_labels or label.lower() in GENERIC_DIRS:
            continue  # already billed, or not a project at all

        debts.append({
            "kind": "dangling_ask",
            "label": label,
            "project": redact(ask["cwd"]),
            "principal_turns": len(session_turns),
            "first_seen": session_turns[0]["ts"].isoformat(),
            "last_seen": session_turns[-1]["ts"].isoformat(),
            "idle_days": idle_days,
            "revisits": 0,
            "revisit_gaps_days": [],
            "mean_revisit_gap_days": None,
            "runtimes": sorted({t["runtime"] for t in session_turns}),
            "sessions": 1,
            "source_refs": build_source_refs(session_turns, ask["cwd"]),
            "unanswered_replies": replies_after,
            "deadline_signals": find_deadline_signals(ask["text"]),
            # 정지 신호는 프로젝트 단위 궤적이 있어야 읽을 수 있다. 단일 세션에는
            # 그 궤적이 없으므로 비운다 — 증거 없이 라벨을 붙이지 않는다.
            "stall_signals": [],
            "last_words": {
                "ts": ask["ts"].isoformat(),
                "text": redact(" ".join(ask["text"].split()))[:400],
            },
        })
    return debts


# --------------------------------------------------------------------------
# 7. Debt #3 — verbal promises
# --------------------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    """Promises live in sentences, not in 4,000-character pasted specs."""
    chunks: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or NOISE_LINE.match(line):
            continue
        for piece in SENTENCE_SPLIT.split(line):
            piece = " ".join(piece.split())
            if MIN_SENTENCE_LEN <= len(piece) <= MAX_SENTENCE_LEN:
                chunks.append(piece)
    return chunks


def find_deadline_signals(text: str) -> list[str]:
    return sorted({label for regex, label in DEADLINE_RES if regex.search(text)})


def build_verbal_promises(turns: list[dict], now: datetime, since: datetime) -> list[dict]:
    compiled = [(re.compile(p, re.I), lab, w) for p, lab, w in DEFERRAL_PATTERNS]
    seen: set[str] = set()
    debts: list[dict] = []

    for turn in turns:
        if turn["role"] != "user" or turn["ts"] < since:
            continue
        for sentence in split_sentences(turn["text"]):
            hit = None
            for regex, label, weight in compiled:
                match = regex.search(sentence)
                if match and not LABEL_USAGE.match(sentence[match.end():]):
                    hit = (label, weight)
                    break
            if hit is None:
                continue
            fingerprint = re.sub(r"\W+", "", sentence)[:80]
            if fingerprint in seen:
                continue  # identical text re-sent is not a second promise
            seen.add(fingerprint)

            label, weight = hit
            debts.append({
                "kind": "verbal_promise",
                "label": path_label(turn["cwd"] or "") or "(unknown)",
                "project": redact(turn["cwd"]),
                "principal_turns": 1,
                "first_seen": turn["ts"].isoformat(),
                "last_seen": turn["ts"].isoformat(),
                "idle_days": (now - turn["ts"]).days,
                "revisits": 0,
                "revisit_gaps_days": [],
                "mean_revisit_gap_days": None,
                "runtimes": [turn["runtime"]],
                "sessions": 1,
                "source_refs": build_source_refs([turn], turn["cwd"]),
                "marker": label,
                "marker_weight": weight,
                "deadline_signals": find_deadline_signals(sentence),
                "stall_signals": [],  # 한 문장에는 궤적이 없다
                "last_words": {"ts": turn["ts"].isoformat(), "text": redact(sentence)[:400]},
            })
            break  # one promise per turn
    return debts


# --------------------------------------------------------------------------
# 8. Invoice arithmetic — 연체 / 이자 / 납부 기한 / 탕감
# --------------------------------------------------------------------------

def project_due(debt: dict, now: datetime) -> dict:
    """
    Forecast when this debt comes due — from evidence, never from vibes.

      1. A deadline the user actually typed.
      2. The observed re-entry rhythm (it resurfaces on schedule).
      3. No basis at all → say so. Do not invent a date.
    """
    if debt["deadline_signals"]:
        horizons = [DUE_HORIZON_DAYS[l] for l in debt["deadline_signals"] if l in DUE_HORIZON_DAYS]
        if horizons:
            return {
                "in_days": min(horizons),
                "basis": "stated_deadline",
                "detail": "본인이 직접 말한 기한 — " + ", ".join(
                    DEADLINE_KO.get(l, l) for l in debt["deadline_signals"]),
                "confidence": "high",
            }

    # A write-off candidate gets no schedule: an old revisit rhythm that has
    # been silent past the write-off line predicts nothing any more, and
    # "탕감 권고인데 납부 기한 0일 뒤"는 자기모순이다.
    if debt["idle_days"] >= WRITE_OFF_DAYS:
        return {
            "in_days": None,
            "basis": "dormant",
            "detail": (f"{debt['idle_days']}일간 돌아오지 않았습니다. "
                       "스스로 다시 열릴 가능성은 낮습니다 — 기한이 아니라 결정이 필요합니다."),
            "confidence": "high",
        }

    gap = debt.get("mean_revisit_gap_days")
    if gap and debt["revisits"] >= 1:
        overdue_against_rhythm = round(debt["idle_days"] - gap, 1)
        return {
            "in_days": max(0, int(round(gap - debt["idle_days"]))),
            "basis": "revisit_rhythm",
            "detail": (f"평균 {gap}일마다 돌아왔는데 이번엔 {debt['idle_days']}일째 "
                       f"({overdue_against_rhythm:+}일)"),
            "confidence": "medium" if debt["revisits"] >= 2 else "low",
        }

    return {
        "in_days": None,
        "basis": "no_basis",
        "detail": "명시된 기한도 재방문 주기도 없음 — 기한을 추정하지 않음",
        "confidence": "none",
    }


KIND_WEIGHT = {"abandoned_project": 1.0, "dangling_ask": 0.85, "verbal_promise": 0.5}


def finalize(debt: dict, now: datetime) -> dict:
    """Attach interest, due date, status, severity, and any sensitivity flag."""
    debt["due"] = project_due(debt, now)

    # Applied to all three debt kinds at once, so a private matter cannot slip
    # onto the bill just because it surfaced as a promise rather than a project.
    quote = (debt.get("last_words") or {}).get("text", "")
    debt["sensitive_topics"] = sensitive_topics(quote) if quote else []
    debt["sensitive_approved"] = False
    refs = debt.get("source_refs") or []
    debt["item_id"] = stable_item_id(
        debt["kind"],
        (refs[0].get("project_path", "") if refs else debt.get("project", "")),
        [ref.get("session_id", "") for ref in refs],
    )
    # The deterministic repayment planner fills this. Keeping the key in the
    # ledger makes the public contract explicit without pretending options
    # were grounded before project rehydration.
    debt["repayment_options"] = []

    # Interest is real: each re-entry meant rebuilding lost context from zero.
    debt["interest"] = {
        "revisits": debt["revisits"],
        "detail": (f"{debt['revisits']}번 다시 열었다가 {debt['revisits']}번 다 떠났습니다"
                   if debt["revisits"] else "재진입 없음 — 한 번 떠난 뒤 그대로"),
    }

    if debt["idle_days"] >= WRITE_OFF_DAYS:
        debt["status"] = "write_off_candidate"
    elif debt["due"]["in_days"] is not None and debt["due"]["in_days"] <= 7:
        debt["status"] = "due_soon"
    else:
        debt["status"] = "overdue"

    debt["severity"] = round(
        KIND_WEIGHT.get(debt["kind"], 0.5)
        * (
            min(debt["principal_turns"], 800) / 100.0     # sunk investment
            + debt["revisits"] * 1.2                      # accrued interest
            + min(debt["idle_days"], 90) / 30.0           # time overdue
            + (2.0 if debt["deadline_signals"] else 0.0)  # a stated deadline
        ),
        2,
    )
    return debt


# --------------------------------------------------------------------------
# 9. Optional: uncommitted work sitting in an abandoned project
# --------------------------------------------------------------------------

def anonymize(debts: list[dict]) -> list[dict]:
    """
    Strip identity, keep arithmetic.

    A bill is a private document, but sometimes you need to show one — to a
    reviewer, a coach, a teammate. This keeps every measured number intact and
    removes everything that says whose life it is.
    """
    # Build every alias before rewriting anything: a stall signal on the first
    # line item can reference a project that appears further down the bill, and
    # a half-built map would call it "다른 프로젝트" while its own line says
    # "프로젝트 B" — the same project under two names in one document.
    alias: dict[str, str] = {}
    for debt in debts:
        if debt["label"] not in alias:
            alias[debt["label"]] = f"프로젝트 {chr(ord('A') + len(alias))}"

    for debt in debts:
        debt["label"] = alias[debt["label"]]
        debt["project"] = "<anonymized>"
        debt["item_id"] = f"lb_public_{debt['label'].split()[-1].lower()}"
        debt["source_refs"] = []

        # A stall signal can name a second project ("you moved to X"). X may not
        # be on the bill at all, so it gets no alias — say "다른 프로젝트" rather
        # than inventing one. The observation survives; the identity does not.
        for signal in debt.get("stall_signals", []):
            referenced = signal.pop("ref", None)
            if referenced is None:
                continue
            signal["detail"] = (
                f"멈춘 지 {SWITCH_WINDOW_DAYS}일 안에 "
                f"{alias.get(referenced, '다른 프로젝트')}가 새로 시작됨"
            )

        # The flag exists so the agent can ask the user privately. On a bill
        # meant to be shown to someone else it is itself the leak — "this
        # person has an unfinished health matter" survives every other
        # redaction. The quote is already hidden; the category goes too.
        debt["sensitive_topics"] = []

        if debt.get("last_words"):
            kind = ("열린 질문" if OPEN_QUESTION.search(debt["last_words"]["text"])
                    else "미완의 요청")
            debt["last_words"] = {
                "ts": debt["last_words"]["ts"],
                "text": f"(인용문 비공개 — {kind} 1건)",
            }
    return debts


STALL_LABEL = {
    "new_project_nearby": "그 무렵 다른 프로젝트가 시작됨",
    "escalating_silence": "간격이 점점 벌어짐",
    "stalled_at_blocker": "인증·결제 단계에서 정지",
    "stalled_before_ship": "배포·게시 직전 정지",
    "repeated_rewrite": "반복해서 다시 시작함",
    "scope_creep": "범위가 커진 채 정지",
}


def summarize_stall_patterns(debts: list[dict]) -> list[dict]:
    """
    Cross-project observation, not a personality read.

    One project stalling before deploy is an incident. Three doing it is a
    pattern worth naming — but it is still stated as a place on the map
    ("여러 건이 여기서 멈췄습니다"), never as a trait ("당신은 ~하는 사람").
    Needs 2+ occurrences: a single hit is noise, and the whole point of this
    section is that repetition is the evidence.
    """
    counts = Counter(
        signal["type"]
        for debt in debts
        for signal in debt.get("stall_signals", [])
    )
    return [
        {
            "type": stype,
            "count": count,
            "label": STALL_LABEL.get(stype, stype),
            "projects": sorted({
                d["label"] for d in debts
                if any(s["type"] == stype for s in d.get("stall_signals", []))
            }),
        }
        for stype, count in counts.most_common()
        if count >= 2
    ]


def check_git(path: str) -> dict | None:
    if not path or not os.path.isdir(os.path.join(path, ".git")):
        return None
    try:
        status = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if status.returncode != 0:
        return None
    dirty = [l for l in status.stdout.splitlines() if l.strip()]
    return {"uncommitted_files": len(dirty)} if dirty else None


# --------------------------------------------------------------------------
# 10. Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Harvest unpaid intentions from local agent history (read-only)."
    )
    ap.add_argument("--days", type=int, default=30,
                    help="billing period for newly-incurred verbal promises (default: 30)")
    ap.add_argument("--sessions-root", default=None, help="override transcript directory")
    ap.add_argument("--max-items", type=int, default=10, help="line items to emit")
    ap.add_argument("--kinds", default="all",
                    help="comma list: abandoned_project,dangling_ask,verbal_promise")
    ap.add_argument("--git", action="store_true", help="also check for uncommitted work")
    ap.add_argument("--demo", action="store_true", help="run against bundled fixture data")
    ap.add_argument("--anonymize", action="store_true",
                    help="keep every number, remove names and quotes (safe to share)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)
    wanted = ({"abandoned_project", "dangling_ask", "verbal_promise"}
              if args.kinds == "all" else set(args.kinds.split(",")))

    files = discover_session_files(args.sessions_root, args.demo)
    turns, parser_stats = read_turns(files)

    debts: list[dict] = []
    project_debts = build_project_debts(turns, now) if "abandoned_project" in wanted else []
    debts.extend(project_debts)
    billed_labels = {d["label"] for d in project_debts}
    if "dangling_ask" in wanted:
        debts.extend(build_dangling_asks(turns, now, billed_labels))
    if "verbal_promise" in wanted:
        debts.extend(build_verbal_promises(turns, now, since))

    debts = [finalize(d, now) for d in debts]
    debts.sort(key=lambda d: d["severity"], reverse=True)
    debts = debts[: args.max_items]

    if args.git:
        for debt in debts:
            info = check_git(debt.get("project", ""))
            if info:
                debt["uncommitted"] = info
                # 미커밋 파일이 쌓인 채로 턴까지 많이 들어간 프로젝트. 두 조건을
                # 모두 요구하는 이유: 파일만 많으면 그냥 큰 프로젝트고, 턴만 많으면
                # 그냥 오래 한 프로젝트다. 둘이 겹칠 때만 "벌여둔 채 멈췄다"가 된다.
                if (info["uncommitted_files"] >= SCOPE_CREEP_MIN_FILES
                        and debt["principal_turns"] >= SCOPE_CREEP_MIN_TURNS):
                    debt.setdefault("stall_signals", []).append({
                        "type": "scope_creep",
                        "detail": (f"커밋되지 않은 파일 {info['uncommitted_files']}개가 "
                                   f"{debt['principal_turns']}턴짜리 작업 위에 남아 있음"),
                        "confidence": "medium",
                    })

    if args.anonymize:
        debts = anonymize(debts)

    # 패턴 집계는 익명화 뒤에 돌린다. 앞에서 돌리면 실명 프로젝트 이름이
    # 패턴 섹션을 통해 그대로 새어나간다.
    stall_patterns = summarize_stall_patterns(debts)

    # ---- honesty gate -----------------------------------------------------
    verdict, notes = "ok", []
    if not files:
        verdict = "insufficient_data"
        notes.append("읽을 수 있는 세션 기록이 없습니다. --sessions-root 로 경로를 지정하거나 --demo 로 실행하세요.")
    elif len(turns) < 30:
        verdict = "insufficient_data"
        notes.append(f"전체 대화가 {len(turns)}건뿐이라 패턴을 신뢰할 수 없습니다.")
    elif not debts:
        verdict = "no_debt"
        notes.append("미납 부채가 없습니다. 청구할 것이 없습니다.")

    kind_counts = Counter(d["kind"] for d in debts)
    document = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "verdict": verdict,
        "notes": notes,
        "billing_period": {
            "from": since.date().isoformat(),
            "to": now.date().isoformat(),
            "days": args.days,
            "note": "중단된 프로젝트는 발생 시점과 무관하게 미납이면 청구됩니다 (연체는 누적).",
        },
        "scan_scope": {
            "transcript_files": len(files),
            "runtimes": sorted({turn["runtime"] for turn in turns}),
            "turns_scanned": len(turns),
            "parser_stats": parser_stats["by_runtime"],
            "read_only": True,
            "network_calls": 0,
            "git_checked": bool(args.git),
        },
        "summary": {
            "line_items": len(debts),
            "by_kind": dict(kind_counts),
            "principal_turns_at_risk": sum(d["principal_turns"] for d in debts),
            "total_interest_revisits": sum(d["revisits"] for d in debts),
            "oldest_debt_days": max((d["idle_days"] for d in debts), default=0),
            "write_off_candidates": sum(1 for d in debts if d["status"] == "write_off_candidate"),
        },
        "stall_patterns": stall_patterns,
        "line_items": debts,
    }

    json.dump(document, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
