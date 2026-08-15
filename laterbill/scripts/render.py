#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laterbill / render.py  —  청구서 조판기

Turns harvest.py's JSON ledger into the actual bill.

This renderer is deliberately dumb: it states only what the ledger contains and
never adds a number the evidence does not support. Interpretation — which debts
to revive, which to forgive — is the agent's job, layered on top of this.

Usage:
    python harvest.py | python render.py
    python harvest.py | python render.py --format html -o bill.html
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime

# Both ends of the pipe must agree on UTF-8. On Windows the default console
# codec is cp949, which turns Korean quotes into unencodable surrogates the
# moment `harvest.py | render.py` is run — the exact command in the README.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    # utf-8-sig, not utf-8: PowerShell inserts a BOM when it pipes between two
    # processes, which makes json.load reject the very command the README leads
    # with. Reading as -sig strips a BOM when present and changes nothing when
    # it is not.
    sys.stdin.reconfigure(encoding="utf-8-sig")

KIND_LABEL = {
    "abandoned_project": "중단된 프로젝트",
    "dangling_ask": "응답 없이 끝난 요청",
    "verbal_promise": "말로 한 약속",
}

STATUS_LABEL = {
    "overdue": "연체",
    "due_soon": "납부 임박",
    "write_off_candidate": "탕감 권고",
}

CONFIDENCE_LABEL = {
    "high": "높음 (본인 발언 근거)",
    "medium": "보통 (재방문 주기 근거)",
    "none": "근거 없음",
}

# 정지 신호는 "어디서 멈췄나"만 말한다. 이름에 원인이나 동기가 들어가지 않도록
# 전부 상황 서술로 짓는다 — "배포가 무서워서"가 아니라 "배포 직전 정지".
STALL_LABEL = {
    "new_project_nearby": "그 무렵 다른 프로젝트가 시작됨",
    "escalating_silence": "간격이 점점 벌어짐",
    "stalled_at_blocker": "인증·결제 단계에서 정지",
    "stalled_before_ship": "배포·게시 직전 정지",
    "repeated_rewrite": "반복해서 다시 시작함",
    "scope_creep": "범위가 커진 채 정지",
}

SENSITIVE_LABEL = {
    "health": "건강",
    "family": "가족",
    "money_work": "금전·고용",
}


def fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso or "-"


def bill_number(doc: dict) -> str:
    stamp = fmt_date(doc.get("generated_at", "")).replace("-", "")
    return f"LB-{stamp}-{doc['summary']['line_items']:02d}"


def resume_command(ref: dict) -> str | None:
    if not ref.get("project_exists"):
        return None
    project = str(ref.get("project_path") or "").replace('"', '\\"')
    session = str(ref.get("session_id") or "").replace('"', '\\"')
    runtime = ref.get("runtime", "")
    if runtime == "codex":
        return f'codex resume -C "{project}" "{session}"'
    if runtime == "claude-code":
        return f'cd "{project}" && claude --resume "{session}"'
    return None


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def render_markdown(doc: dict) -> str:
    period = doc["billing_period"]
    summary = doc["summary"]
    scope = doc["scan_scope"]
    out: list[str] = []
    add = out.append

    add("# 하다 만 일 종결반 (Laterbill)")
    add("")
    add("> 당신이 “나중에 하자”고 말한 순간, 반려에이전트는 조용히 장부에 적었습니다.")
    add("")
    add(f"| | |\n|---|---|")
    add(f"| 청구 번호 | `{bill_number(doc)}` |")
    add(f"| 청구 기간 | {period['from']} ~ {period['to']} ({period['days']}일) |")
    add("| 채권자 | 과거의 나 |")
    add("| 채무자 | 오늘의 나 |")
    add("| 발행 | 반려에이전트 |")
    add(f"| 조사 범위 | 기록 {scope['transcript_files']}개 · 대화 {scope['turns_scanned']:,}턴 · "
        f"{', '.join(scope['runtimes'])} |")
    add("")

    if doc["verdict"] != "ok":
        add(f"## ⚠ {doc['verdict']}")
        add("")
        for note in doc["notes"]:
            add(f"- {note}")
        add("")
        add("_증거가 부족하면 청구서를 발행하지 않습니다. 없는 빚을 지어내지 않습니다._")
        return "\n".join(out)

    add("## 총계")
    add("")
    add("| 항목 | 값 |")
    add("|---|---|")
    add(f"| 미납 항목 | **{summary['line_items']}건** |")
    add(f"| 묶여 있는 원금 | **{summary['principal_turns_at_risk']:,}턴** |")
    add(f"| 최장 연체 | **{summary['oldest_debt_days']}일** |")
    add(f"| 누적 이자 | 재진입 {summary['total_interest_revisits']}회 |")
    add(f"| 탕감 권고 | {summary['write_off_candidates']}건 |")
    add("")
    add("<sub>원금 = 이 일에 이미 쏟아부은 대화 턴 수. 이자 = 다시 열었다가 또 떠나며 "
        "맥락을 처음부터 다시 쌓아야 했던 횟수.</sub>")
    add("")

    # 한 건이 그 지점에서 멈춘 건 사건이고, 여러 건이 같은 지점에서 멈춘 건
    # 지도 위의 위치다. 사람에 대한 판정이 아니라 장부에 반복해 찍힌 좌표다.
    patterns = doc.get("stall_patterns") or []
    if patterns:
        add("## 반복해서 멈추는 지점")
        add("")
        add("| 지점 | 건수 | 해당 항목 |")
        add("|---|---|---|")
        for pattern in patterns:
            add(f"| {pattern['label']} | {pattern['count']}건 | "
                + ", ".join(f"`{name}`" for name in pattern["projects"]) + " |")
        add("")
        add("<sub>이건 사람에 대한 판정이 아니라 장부에 반복해 찍힌 좌표입니다. "
            "같은 지점에서 여러 번 멈췄다면, 다음에 그 지점에 닿기 전에 미리 준비할 수 있습니다.</sub>")
        add("")

    add("## 청구 내역")
    add("")
    for index, item in enumerate(doc["line_items"], start=1):
        add(f"### {index}. {item['label']}  —  연체 {item['idle_days']}일")
        add("")
        add(f"- **유형** · {KIND_LABEL.get(item['kind'], item['kind'])} "
            f"／ **상태** · {STATUS_LABEL.get(item['status'], item['status'])}")
        add(f"- **원금** · {item['principal_turns']:,}턴 "
            f"({item['sessions']}개 세션, {fmt_date(item['first_seen'])} 시작)")
        add(f"- **이자** · {item['interest']['detail']}")
        if item.get("revisit_gaps_days"):
            add(f"- **재진입 간격** · {', '.join(f'{g}일' for g in item['revisit_gaps_days'])}")
        due = item["due"]
        due_text = f"{due['in_days']}일 뒤" if due["in_days"] is not None else "추정 불가"
        add(f"- **납부 기한** · {due_text} — {due['detail']} "
            f"(확신도: {CONFIDENCE_LABEL.get(due['confidence'], due['confidence'])})")
        for signal in item.get("stall_signals", []):
            add(f"- **정지 신호** · {STALL_LABEL.get(signal['type'], signal['type'])} — "
                f"{signal['detail']}")
        if item.get("uncommitted"):
            add(f"- **미커밋 작업** · {item['uncommitted']['uncommitted_files']}개 파일이 "
                "커밋되지 않은 채 남아 있습니다")
        refs = item.get("source_refs") or []
        if refs:
            ref = refs[0]
            if ref.get("runtime") == "demo":
                add("- **원본 프로젝트** · 합성 데모 — 실제 기록에서는 프로젝트 경로와 재개 명령 제공")
            else:
                add(f"- **원본 프로젝트** · `{ref.get('project_path', '')}`")
                command = resume_command(ref)
                if command:
                    add(f"- **마지막 대화 재개** · `{command}`")
                else:
                    add("- **마지막 대화 재개** · 프로젝트 위치를 찾을 수 없음 — 위치 복구부터 필요")

        sensitive_waiting = bool(
            item.get("sensitive_topics") and not item.get("sensitive_approved")
        )
        if item.get("last_words") and not sensitive_waiting:
            add("")
            add(f"**마지막으로 남긴 말** ({fmt_date(item['last_words']['ts'])})")
            add("")
            quote = item["last_words"]["text"].replace("\n", " ")
            add(f"> {quote}")
        if sensitive_waiting:
            add("")
            add("<sub>⚠ 사적인 사안이 감지되어 원문과 상환안은 승인 전 비공개입니다. "
                "내용을 다시 읊지 않고 포함 여부부터 확인합니다.</sub>")

        options = item.get("repayment_options") or []
        if options:
            add("")
            add("**상환안**")
            add("")
            add("| 안 | 전략 | 지금 바로 할 일 | 여기까지 되면 끝 | 시간 | 장단점 |")
            add("|---|---|---|---|---:|---|")
            for option in options:
                mark = " ★ 추천" if option.get("recommended") else ""
                add(f"| {option['option_id']}{mark} | {option['title']} | "
                    f"{option['first_action']} | {option['done_when']} | "
                    f"{option['timebox']}분 | {option['tradeoff']} |")
        elif item.get("repayment_note"):
            add("")
            add(f"_상환안: {item['repayment_note']}_")

        plan = item.get("repayment_plan")
        if plan:
            add("")
            add(f"**선택한 {plan['selected_option']}안 상세계획 · {plan['timebox']}분**")
            add("")
            for task_index, task in enumerate(plan.get("tasks", []), start=1):
                area = ", ".join(task.get("files_or_area") or [])
                add(f"{task_index}. `{area}` — {task['command_or_action']} "
                    f"**여기까지 되면 끝:** {task['done_when']}")
            improve = plan.get("self_improvement") or {}
            if improve:
                add("")
                add(f"- **자가개선 가드레일** · {improve['guardrail']}")
                add(f"- **개선 판정** · {improve['success_signal']}")
        settlement = item.get("settlement_record")
        if settlement:
            add("")
            add(f"**탕감 기록** · {settlement['reason']} — 실행 작업 0개")
        add("")

    add("## 앞으로 30일 — 납부 예정표")
    add("")
    scheduled = [i for i in doc["line_items"] if i["due"]["in_days"] is not None]
    scheduled.sort(key=lambda i: i["due"]["in_days"])
    if scheduled:
        add("| 예상 시점 | 항목 | 근거 | 확신도 |")
        add("|---|---|---|---|")
        for item in scheduled:
            add(f"| D+{item['due']['in_days']} | {item['label']} | {item['due']['detail']} | "
                f"{item['due']['confidence']} |")
    else:
        add("근거 있는 기한이 있는 항목이 없습니다. **일정을 지어내지 않습니다.**")
    add("")

    unscheduled = [i for i in doc["line_items"] if i["due"]["in_days"] is None]
    silent = [i for i in unscheduled if i["due"]["basis"] != "dormant"]
    dormant = [i for i in unscheduled if i["due"]["basis"] == "dormant"]
    if silent:
        add(f"기한 미정 {len(silent)}건 — 근거가 생길 때까지 날짜를 지어내지 않습니다: "
            + ", ".join(f"`{i['label']}`" for i in silent))
        add("")
    if dormant:
        add(f"만기 없음 {len(dormant)}건 — 예측이 아니라 결정을 기다립니다: "
            + ", ".join(f"`{i['label']}`({i['idle_days']}일)" for i in dormant))
        add("")

    add("## 처리 옵션")
    add("")
    add("각 항목에 대해 셋 중 하나를 고르세요. **미루기는 선택지에 없습니다.**")
    add("")
    add("1. **상환** — 지금 다시 엽니다. 반려에이전트가 마지막 맥락부터 이어서 시작합니다.")
    add("2. **분납** — 오늘은 30분만. 다음 한 걸음만 정하고 닫습니다.")
    add("3. **탕감** — 정식으로 놓아줍니다. 실패가 아니라 종결입니다.")
    add("")
    write_offs = [i for i in doc["line_items"] if i["status"] == "write_off_candidate"]
    if write_offs:
        add(f"**탕감 권고 {len(write_offs)}건** — "
            + ", ".join(f"`{i['label']}`({i['idle_days']}일)" for i in write_offs)
            + " · 두 달 넘게 돌아가지 않았다면 그건 미루는 게 아니라 이미 끝난 일입니다. "
              "장부에서 지워야 남은 항목이 보입니다.")
        add("")

    add("---")
    add("")
    add(f"<sub>읽기 전용으로 수집했습니다. 외부 전송 {scope['network_calls']}건. "
        "이메일·토큰·전화번호·홈 경로는 인용문에서 마스킹했습니다. "
        "이 청구서는 당신을 평가하지 않습니다 — 장부를 보여줄 뿐입니다.</sub>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

# A bill should look like a bill. The palette and the typographic rules below
# are the skillthon's own — oatmeal paper, deep teal ink, no rounded corners
# anywhere, headlines set large with tight negative tracking. Everything here is
# a paper document: ruled rows, dotted leaders, tabular figures, a rubber stamp,
# and a tear-off stub at the foot.
#
# No web font is fetched. Pretendard is used when the reader already has it and
# the stack falls back to the platform UI face otherwise, so the page stays
# self-contained and works offline.
HTML_SHELL = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>하다 만 일 종결반 (Laterbill) · {bill_no}</title>
<style>
  :root {{
    --paper:#F4F0E6; --sheet:#FBF9F3; --ink:#171916; --teal:#00756E;
    --teal-pale:#E8F2EF; --teal-bright:#80D0C9; --muted:#5E625D;
    --rule:#BFC5BF; --brick:#A63D2F;
    --sans:"Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,
           "Segoe UI","Malgun Gothic",sans-serif;
    --mono:"SFMono-Regular",Menlo,Consolas,"D2Coding",monospace;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; padding:clamp(1rem,4vw,3rem) 1rem; background:var(--paper);
    color:var(--ink); font-family:var(--sans); line-height:1.65;
    -webkit-font-smoothing:antialiased;
  }}
  .sheet {{
    max-width:780px; margin:0 auto; background:var(--sheet);
    border:1px solid var(--ink); padding:clamp(1.5rem,5vw,3.5rem);
  }}

  /* ---- letterhead ---- */
  .head {{ position:relative; }}
  h1 {{
    margin:0; font-size:clamp(2.6rem,9vw,4.4rem); font-weight:700;
    letter-spacing:-0.055em; line-height:0.95;
  }}
  .kicker {{
    display:flex; flex-wrap:wrap; gap:.5rem 1.25rem; align-items:baseline;
    margin-top:1rem; font-family:var(--mono); font-size:.9rem; line-height:1.5;
    letter-spacing:.1em; text-transform:uppercase; color:var(--teal);
  }}
  .kicker b {{ color:var(--ink); font-weight:700; }}
  .stamp {{
    position:absolute; top:-.5rem; right:0; transform:rotate(-9deg);
    border:2px solid var(--brick); color:var(--brick); padding:.35rem .7rem .3rem;
    text-align:center; line-height:1.1; opacity:.9;
  }}
  .stamp .big {{
    display:block; font-size:1.35rem; font-weight:700; letter-spacing:-0.03em;
  }}
  .stamp .small {{
    display:block; font-family:var(--mono); font-size:.58rem; letter-spacing:.14em;
  }}
  .bar {{ height:4px; background:var(--ink); margin:1.5rem 0 0; }}

  /* ---- ruled meta rows ---- */
  .rows {{ margin:0 0 2.5rem; }}
  .row {{
    display:flex; justify-content:space-between; gap:1rem;
    padding:.55rem 0; border-bottom:1px solid var(--rule); font-size:.88rem;
  }}
  .row dt {{ color:var(--muted); margin:0; white-space:nowrap; }}
  .row dd {{ margin:0; text-align:right; font-variant-numeric:tabular-nums; }}

  /* ---- section headings ---- */
  h2 {{
    margin:2.75rem 0 1rem; font-size:clamp(1.5rem,4vw,2.1rem); font-weight:700;
    letter-spacing:-0.045em;
  }}
  h2 .n {{ font-family:var(--mono); font-size:.6em; color:var(--teal);
           letter-spacing:.1em; margin-right:.6rem; }}

  /* ---- totals ---- */
  /* 칸 사이 1px 간격에 배경색이 비쳐 구분선이 된다. 좁은 화면에서 2×2 로 접히든
     한 줄로 펴지든 선이 알아서 맞는다 — border 로 그으면 접힐 때 행 사이가 빈다. */
  .totals {{
    display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
    gap:1px; border:1px solid var(--ink); background:var(--rule);
  }}
  .cell {{ padding:1.1rem 1.2rem; background:var(--teal-pale); }}
  .cell .k {{ font-size:.72rem; color:var(--muted); letter-spacing:.02em; }}
  .cell .v {{
    display:block; margin-top:.25rem; font-size:1.9rem; font-weight:700;
    letter-spacing:-0.05em; font-variant-numeric:tabular-nums; line-height:1.1;
  }}
  .cell .v u {{ font-size:.9rem; font-weight:400; letter-spacing:0;
                text-decoration:none; margin-left:.15em; }}
  .cell.hero {{ background:var(--teal); color:#fff; }}
  .cell.hero .k {{ color:var(--teal-bright); }}
  .note {{ margin:.75rem 0 0; font-size:.9rem; line-height:1.65; color:var(--muted); }}

  /* ---- pattern table ---- */
  table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
  th,td {{ text-align:left; padding:.6rem .5rem; border-bottom:1px solid var(--rule); }}
  th {{ font-size:.92rem; line-height:1.4; font-weight:800; letter-spacing:.04em;
        color:var(--ink); border-bottom:1px solid var(--ink); }}
  td.num {{ font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .repayment-table th:last-child,
  .repayment-table td:last-child {{ width:1%; white-space:nowrap; }}

  /* ---- line items ---- */
  .item {{ margin:2rem 0; padding-top:1.25rem; border-top:1px solid var(--rule); }}
  .item:first-of-type {{ border-top:0; }}
  .item-head {{ display:flex; gap:.9rem; align-items:flex-start; }}
  .idx {{
    flex:0 0 auto; width:1.9rem; height:1.9rem; background:var(--ink); color:var(--sheet);
    font-family:var(--mono); font-size:.85rem; display:flex; align-items:center;
    justify-content:center; margin-top:.2rem;
  }}
  .item h3 {{ margin:0; font-size:1.3rem; font-weight:700; letter-spacing:-0.035em;
              line-height:1.25; }}
  .days {{ display:block; margin-top:.2rem; font-size:.8rem; color:var(--brick);
           font-weight:700; font-variant-numeric:tabular-nums; }}
  .days.calm {{ color:var(--muted); }}
  .facts {{ margin:1rem 0 0; padding:0 0 0 2.8rem; }}
  .fact {{
    display:flex; align-items:baseline; gap:.4rem; padding:.28rem 0; font-size:.85rem;
  }}
  .fact .lbl {{ color:var(--muted); white-space:nowrap; }}
  .fact .dots {{ flex:1; border-bottom:1px dotted var(--rule); transform:translateY(-.2em); }}
  .fact .val {{ text-align:right; font-variant-numeric:tabular-nums; }}
  /* 정지 신호는 수치가 아니라 문장이다. 점선 리더로 오른쪽 끝에 밀어 붙이면
     줄바꿈이 생기며 리더가 짓눌린다. 왼쪽 정렬 블록으로 따로 놓는다. */
  .sig {{
    display:flex; gap:.5rem; margin:.3rem 0 0; padding:.4rem .7rem;
    background:var(--teal-pale); font-size:.82rem; line-height:1.5;
  }}
  .sig b {{ color:var(--teal); white-space:nowrap; font-weight:700; }}
  .sig span {{ color:var(--ink); }}
  blockquote {{
    margin:1rem 0 0 2.8rem; padding:.9rem 1.1rem; background:#fff;
    border-left:3px solid var(--teal); font-size:.92rem;
  }}
  blockquote p {{ margin:0; }}
  blockquote cite {{
    display:block; margin-top:.5rem; font-family:var(--mono); font-size:.82rem;
    line-height:1.5; letter-spacing:.06em; color:var(--muted); font-style:normal;
  }}
  .warn {{
    margin:.75rem 0 0 2.8rem; padding:.6rem .8rem; border:1px dashed var(--brick);
    font-size:.78rem; color:var(--brick);
  }}

  /* ---- tear-off stub ---- */
  .stub {{ margin-top:3rem; border-top:2px dashed var(--ink); padding-top:1.5rem; }}
  .stub .perf {{
    font-family:var(--mono); font-size:.82rem; font-weight:700;
    letter-spacing:.2em; color:var(--muted);
    text-align:center; margin:-2.1rem 0 1.5rem;
  }}
  .stub .perf span {{ background:var(--sheet); padding:0 .7rem; }}
  .choices {{
    display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
    gap:1px; background:var(--ink); border:1px solid var(--ink);
  }}
  .choice {{ background:var(--sheet); padding:1rem 1.1rem; }}
  .choice b {{ display:block; font-size:1.05rem; letter-spacing:-0.02em; }}
  .choice span {{ display:block; margin-top:.3rem; font-size:.78rem; color:var(--muted); }}

  footer {{
    margin-top:2rem; padding-top:1rem; border-top:1px solid var(--rule);
    font-size:.72rem; color:var(--muted);
  }}
  .verdict {{ border:2px solid var(--ink); padding:1.5rem; margin:2rem 0; }}
  .verdict h2 {{ margin-top:0; }}
  @media print {{ body {{ background:#fff; padding:0; }} .sheet {{ border:0; }} }}
</style>
<div class="sheet">{body}</div>
"""


def letterhead(doc: dict, stamp: str = "") -> str:
    esc = html.escape
    scope = doc["scan_scope"]
    return (
        "<div class='head'>"
        f"{stamp}"
        "<h1>하다 만 일<br>종결반</h1>"
        "<div class='kicker'>"
        "<span>THE LATER BILL</span>"
        f"<span><b>{esc(bill_number(doc))}</b></span>"
        f"<span>기록 {scope['transcript_files']} · 대화 {scope['turns_scanned']:,}턴</span>"
        "</div></div><div class='bar'></div>"
    )


def fact(label: str, value: str, signal: bool = False) -> str:
    """One ruled line with a dotted leader, the way a paper bill sets them."""
    cls = " signal" if signal else ""
    return (f"<div class='fact{cls}'><span class='lbl'>{label}</span>"
            f"<span class='dots'></span><span class='val'>{value}</span></div>")


def render_html(doc: dict) -> str:
    esc = html.escape
    parts: list[str] = []
    period, summary = doc["billing_period"], doc["summary"]

    if doc["verdict"] != "ok":
        notes = "".join(f"<div class='fact'><span class='lbl'>{esc(n)}</span></div>"
                        for n in doc["notes"])
        parts.append(letterhead(doc))
        parts.append(
            f"<div class='verdict'><h2><span class='n'>!</span>{esc(doc['verdict'])}</h2>"
            f"{notes}<p class='note'>증거가 부족하면 청구서를 발행하지 않습니다. "
            "없는 빚을 지어내지 않습니다.</p></div>"
        )
        return HTML_SHELL.format(bill_no=esc(bill_number(doc)), body="".join(parts))

    stamp = (
        "<div class='stamp'>"
        f"<span class='big'>미납 {summary['line_items']}건</span>"
        f"<span class='small'>OVERDUE {summary['oldest_debt_days']}D</span>"
        "</div>"
    )
    parts.append(letterhead(doc, stamp))

    parts.append(
        "<dl class='rows'>"
        f"<div class='row'><dt>청구 기간</dt><dd>{esc(period['from'])} — {esc(period['to'])}</dd></div>"
        "<div class='row'><dt>채권자</dt><dd>과거의 나</dd></div>"
        "<div class='row'><dt>채무자</dt><dd>오늘의 나</dd></div>"
        "<div class='row'><dt>발행</dt><dd>반려에이전트</dd></div>"
        "</dl>"
    )

    # 이자를 강조 칸에 둔다. 이 도구가 유일하게 재는 값이고, 나머지 셋은
    # 어느 회고 도구나 낼 수 있는 숫자다.
    parts.append(
        "<h2><span class='n'>01</span>총계</h2>"
        "<div class='totals'>"
        f"<div class='cell'><span class='k'>미납 항목</span>"
        f"<span class='v'>{summary['line_items']}<u>건</u></span></div>"
        f"<div class='cell'><span class='k'>묶여 있는 원금</span>"
        f"<span class='v'>{summary['principal_turns_at_risk']:,}<u>턴</u></span></div>"
        f"<div class='cell hero'><span class='k'>누적 이자 · 재진입</span>"
        f"<span class='v'>{summary['total_interest_revisits']}<u>회</u></span></div>"
        f"<div class='cell'><span class='k'>최장 연체</span>"
        f"<span class='v'>{summary['oldest_debt_days']}<u>일</u></span></div>"
        "</div>"
        "<p class='note'>원금은 이 일에 이미 쏟아부은 대화 턴 수, 이자는 다시 열었다가 또 떠나며 "
        "맥락을 처음부터 다시 쌓아야 했던 횟수입니다.</p>"
    )

    patterns = doc.get("stall_patterns") or []
    if patterns:
        rows = "".join(
            f"<tr><td>{esc(p['label'])}</td><td class='num'>{p['count']}건</td>"
            f"<td>{esc(', '.join(p['projects']))}</td></tr>"
            for p in patterns
        )
        parts.append(
            "<h2><span class='n'>02</span>반복해서 멈추는 지점</h2>"
            f"<table><tr><th>지점</th><th>건수</th><th>해당 항목</th></tr>{rows}</table>"
            "<p class='note'>사람에 대한 판정이 아니라 장부에 반복해 찍힌 좌표입니다.</p>"
        )

    parts.append(f"<h2><span class='n'>{'03' if patterns else '02'}</span>청구 내역</h2>")

    for index, item in enumerate(doc["line_items"], start=1):
        due = item["due"]
        due_text = f"{due['in_days']}일 뒤" if due["in_days"] is not None else "추정 불가"
        calm = " calm" if item["status"] == "write_off_candidate" else ""

        facts = [
            fact("유형", esc(KIND_LABEL.get(item["kind"], item["kind"]))),
            fact("상태", esc(STATUS_LABEL.get(item["status"], item["status"]))),
            fact("원금", f"{item['principal_turns']:,}턴"),
            fact("이자", esc(item["interest"]["detail"])),
        ]
        if item.get("revisit_gaps_days"):
            facts.append(fact("재진입 간격",
                              ", ".join(f"{g}일" for g in item["revisit_gaps_days"])))
        facts.append(fact("납부 기한", f"{esc(due_text)} · {esc(due['detail'])}"))
        if item.get("uncommitted"):
            facts.append(fact("미커밋 작업",
                              f"{item['uncommitted']['uncommitted_files']}개 파일"))

        signals = "".join(
            f"<div class='sig'><b>{esc(STALL_LABEL.get(s['type'], s['type']))}</b>"
            f"<span>{esc(s['detail'])}</span></div>"
            for s in item.get("stall_signals", [])
        )

        source = ""
        refs = item.get("source_refs") or []
        if refs:
            ref = refs[0]
            if ref.get("runtime") == "demo":
                source = ("<div class='sig'><b>원본 프로젝트</b>"
                          "<span>합성 데모 — 실제 기록에서는 프로젝트 경로와 재개 명령 제공</span></div>")
            else:
                command = resume_command(ref)
                source = (
                    "<div class='sig'><b>원본 프로젝트</b>"
                    f"<span>{esc(ref.get('project_path', ''))}</span></div>"
                    "<div class='sig'><b>마지막 대화 재개</b>"
                    f"<span>{esc(command or '프로젝트 위치를 찾을 수 없음 — 위치 복구부터 필요')}</span></div>"
                )

        sensitive_waiting = bool(
            item.get("sensitive_topics") and not item.get("sensitive_approved")
        )
        quote = ""
        if item.get("last_words") and not sensitive_waiting:
            quote = (
                "<blockquote><p>"
                f"{esc(item['last_words']['text'])}</p>"
                f"<cite>마지막으로 남긴 말 · {fmt_date(item['last_words']['ts'])}</cite>"
                "</blockquote>"
            )

        warn = ""
        if sensitive_waiting:
            warn = ("<div class='warn'>사적인 사안이 감지되어 원문과 상환안은 승인 전 "
                    "비공개입니다. 내용 대신 포함 여부부터 확인합니다.</div>")

        options_html = ""
        options = item.get("repayment_options") or []
        if options:
            rows = "".join(
                "<tr>"
                f"<td><b>{esc(o['option_id'])}{' ★' if o.get('recommended') else ''}</b></td>"
                f"<td>{esc(o['title'])}</td><td>{esc(o['first_action'])}</td>"
                f"<td>{esc(o['done_when'])}</td><td>{o['timebox']}분</td>"
                "</tr>" for o in options
            )
            options_html = (
                "<h4>상환안</h4><table class='repayment-table'><tr><th>안</th><th>전략</th><th>지금 바로 할 일</th>"
                f"<th>여기까지 되면 끝</th><th>시간</th></tr>{rows}</table>"
            )
        elif item.get("repayment_note"):
            options_html = f"<p class='note'>상환안: {esc(item['repayment_note'])}</p>"

        plan_html = ""
        plan = item.get("repayment_plan")
        if plan:
            task_rows = "".join(
                f"<li><b>{esc(', '.join(t.get('files_or_area') or []))}</b> — "
                f"{esc(t['command_or_action'])}<br><small>여기까지 되면 끝: {esc(t['done_when'])}</small></li>"
                for t in plan.get("tasks", [])
            )
            improve = plan.get("self_improvement") or {}
            improve_html = (
                "<div class='sig'><b>자가개선 가드레일</b>"
                f"<span>{esc(improve.get('guardrail', ''))}</span></div>"
                "<div class='sig'><b>개선 판정</b>"
                f"<span>{esc(improve.get('success_signal', ''))}</span></div>"
                if improve else ""
            )
            plan_html = (
                f"<h4>선택한 {esc(plan['selected_option'])}안 상세계획 · {plan['timebox']}분</h4>"
                f"<ol>{task_rows}</ol>{improve_html}"
            )
        settlement_html = ""
        if item.get("settlement_record"):
            settlement = item["settlement_record"]
            settlement_html = (
                "<div class='warn'><b>탕감 기록</b><br>"
                f"{esc(settlement['reason'])} · 실행 작업 0개</div>"
            )

        parts.append(
            "<div class='item'><div class='item-head'>"
            f"<div class='idx'>{index}</div>"
            f"<div><h3>{esc(item['label'])}</h3>"
            f"<span class='days{calm}'>연체 {item['idle_days']}일</span></div>"
            f"</div><div class='facts'>{''.join(facts)}{signals}{source}</div>"
            f"{quote}{warn}{options_html}{plan_html}{settlement_html}</div>"
        )

    write_offs = [i for i in doc["line_items"] if i["status"] == "write_off_candidate"]
    write_off_line = ""
    if write_offs:
        names = ", ".join(f"{esc(i['label'])}({i['idle_days']}일)" for i in write_offs)
        write_off_line = (
            f"<p class='note'><b>탕감 권고 {len(write_offs)}건</b> — {names} · "
            "두 달 넘게 돌아가지 않았다면 그건 미루는 게 아니라 이미 끝난 일입니다.</p>"
        )

    parts.append(
        "<div class='stub'><div class='perf'><span>절취선</span></div>"
        "<h2 style='margin-top:0'>처리 옵션</h2>"
        "<p class='note' style='margin-bottom:1.25rem'>각 항목에 대해 셋 중 하나를 고르세요. "
        "<b>미루기는 선택지에 없습니다.</b></p>"
        "<div class='choices'>"
        "<div class='choice'><b>상환</b><span>지금 다시 엽니다. 마지막 맥락부터 이어서.</span></div>"
        "<div class='choice'><b>분납</b><span>오늘은 30분만. 다음 한 걸음만 정하고 닫습니다.</span></div>"
        "<div class='choice'><b>탕감</b><span>정식으로 놓아줍니다. 실패가 아니라 종결입니다.</span></div>"
        "</div>"
        f"{write_off_line}</div>"
    )

    parts.append(
        "<footer>읽기 전용으로 수집했습니다 · 외부 전송 "
        f"{doc['scan_scope']['network_calls']}건 · 이메일·토큰·전화번호·홈 경로는 "
        "인용문에서 마스킹했습니다<br>"
        "이 청구서는 당신을 평가하지 않습니다. 장부를 보여줄 뿐입니다.</footer>"
    )
    return HTML_SHELL.format(bill_no=esc(bill_number(doc)), body="".join(parts))


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a Later Bill from harvest.py JSON.")
    ap.add_argument("--format", choices=["md", "html"], default="md")
    ap.add_argument("-i", "--input", default="-", help="JSON file, or '-' for stdin")
    ap.add_argument("-o", "--output", default="-", help="output file, or '-' for stdout")
    args = ap.parse_args()

    if args.input == "-":
        doc = json.load(sys.stdin)
    else:
        with open(args.input, "r", encoding="utf-8-sig") as fh:
            doc = json.load(fh)

    text = render_markdown(doc) if args.format == "md" else render_html(doc)
    text = text.encode("utf-8", errors="replace").decode("utf-8")

    if args.output == "-":
        sys.stdout.write(text + "\n")
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
