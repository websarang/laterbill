#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laterbill / make_fixture.py

Generates the bundled demo transcript so `harvest.py --demo` works on a machine
with no history of its own — a reviewer's machine, a fresh container, a laptop
that has never run an agent before.

The data is synthetic and clearly fictional. It exists so the pipeline can be
verified end to end without touching anyone's real records.

    python scripts/make_fixture.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NOW = datetime.now(timezone.utc)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "fixtures", "demo-sessions.jsonl")

# (folder, session, turns, started_days_ago, last_touch_days_ago, revisit_offsets,
#  parting_words, interjections)
#
# `interjections` are (days_ago, text) remarks dropped inside an active burst.
# They exist so the stall-signal detectors have something real to find: a
# fixture where nothing ever stalls cannot demonstrate that the detectors work.
# They sit inside bursts on purpose — placing one in a silent stretch would
# invent a re-entry and corrupt the interest arithmetic.
PROJECTS = [
    (
        "todo-app", "demo-todo", 340, 41, 26, [33, 29],
        "로그인은 되는데 새로고침하면 세션이 풀려. 어디에 저장해야 맞아?",
        [],
    ),
    (
        "blog-migration", "demo-blog", 186, 24, 9, [16],
        "이번 주까지 옮겨야 하는데 이미지 경로는 어떻게 일괄로 바꿔? 그것만 되면 바로 게시할 거야.",
        [],
    ),
    (
        "thesis-figures", "demo-thesis", 96, 78, 71, [],
        "그래프 색이 색각 이상 기준에 맞는지 확인해줘.",
        [],
    ),
    (
        "crawler", "demo-crawler", 74, 22, 5, [17, 12, 8],
        "차단당하는 것 같은데 요청 간격을 얼마로 두면 될까?",
        [],
    ),
    # Widening re-entry gaps (3.3 → 13.7 days), three restarts, and a parting
    # message sitting one step short of shipping.
    (
        "portfolio-site", "demo-portfolio", 210, 60, 9, [55, 46, 30],
        "배포 직전인데 빌드가 자꾸 실패해. 어디부터 봐야 할까?",
        [
            (59, "레이아웃이 자꾸 깨져서 이 부분은 처음부터 다시 짜는 게 나을까?"),
            (53, "구조가 마음에 안 드는데 컴포넌트 나누는 걸 새로 만들어 보자."),
            (44, "지금 코드 리팩터링부터 하고 넘어가자."),
        ],
    ),
]

VERBAL = (
    "crawler", "demo-crawler",
    "파서 중복되는 부분 리팩터링은 나중에 하자. 일단 넘어가고 돌아가는 것부터 보자.",
    6,
)

ASSISTANT_FILLER = "확인했습니다. 해당 부분을 살펴보겠습니다."
USER_FILLER = "그 다음 단계도 이어서 진행해줘."


# Half the demo projects carry Windows paths and half POSIX ones. Transcripts
# travel between machines, so the fixture exercises both separator styles no
# matter which OS the reviewer runs it on — a Windows path read on a Mac used
# to yield a project literally named `C:\demo\todo-app`.
POSIX_PROJECTS = {"blog-migration", "crawler"}


def demo_cwd(folder: str) -> str:
    return f"/home/demo/{folder}" if folder in POSIX_PROJECTS else f"C:\\demo\\{folder}"


def record(kind: str, ts: datetime, session: str, cwd: str, text: str) -> dict:
    """One transcript line, in the same shape a real runtime writes."""
    content = text if kind == "user" else [{"type": "text", "text": text}]
    return {
        "type": kind,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "sessionId": session,
        "cwd": demo_cwd(cwd),
        "isSidechain": False,
        "message": {"role": kind, "content": content},
    }


def main() -> int:
    lines: list[dict] = []

    for folder, session, turns, started, last_touch, revisits, parting, asides in PROJECTS:
        start_ts = NOW - timedelta(days=started)
        end_ts = NOW - timedelta(days=last_touch)

        # Spread turns across the active windows. Each burst is packed into the
        # front of its window so the tail stays silent — that silence is what
        # makes the next turn read as a genuine re-entry rather than one long
        # continuous session.
        boundaries = [start_ts] + [NOW - timedelta(days=d) for d in revisits] + [end_ts]
        windows = max(1, len(boundaries) - 1)
        pairs_per_window = max(2, turns // (2 * windows))
        burst_fraction = 0.35

        for index in range(windows):
            window_start, window_end = boundaries[index], boundaries[index + 1]
            span = max((window_end - window_start).total_seconds(), 3600.0)
            burst = span * burst_fraction
            for step in range(pairs_per_window):
                ts = window_start + timedelta(seconds=burst * step / pairs_per_window)
                lines.append(record("user", ts, session, folder, USER_FILLER))
                lines.append(record("assistant", ts + timedelta(seconds=20),
                                    session, folder, ASSISTANT_FILLER))

        for days_ago, text in asides:
            aside_ts = NOW - timedelta(days=days_ago)
            lines.append(record("user", aside_ts, session, folder, text))
            lines.append(record("assistant", aside_ts + timedelta(seconds=20),
                                session, folder, ASSISTANT_FILLER))

        # The thing they were saying when they walked away.
        lines.append(record("user", end_ts - timedelta(minutes=2), session, folder, parting))
        lines.append(record("assistant", end_ts, session, folder,
                            "확인해 보겠습니다. 잠시만요."))

    folder, session, text, days_ago = VERBAL
    lines.append(record("user", NOW - timedelta(days=days_ago), session, folder, text))

    lines.sort(key=lambda r: r["timestamp"])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    print(f"wrote {OUT}  ({len(lines)} lines, anchored at {NOW.date().isoformat()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
