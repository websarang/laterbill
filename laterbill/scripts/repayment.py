#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build evidence-grounded repayment options and a read-only re-entry plan."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

SIGNAL_GUARDRAILS = {
    "stalled_at_blocker": (
        "인증·결제 단계에서 기록이 멈춤",
        "기능 구현 전에 최소 재현과 필요한 권한·설정을 체크리스트로 고정",
    ),
    "stalled_before_ship": (
        "배포·게시 직전에서 기록이 멈춤",
        "작업 시작 시 빌드·테스트·배포 확인 순서를 완료 기준에 포함",
    ),
    "repeated_rewrite": (
        "기존 작업을 다시 시작한 기록이 반복됨",
        "새로 작성하기 전에 유지할 결과와 폐기 기준을 먼저 기록",
    ),
    "scope_creep": (
        "열린 작업 범위가 커진 채 기록이 멈춤",
        "한 번에 닫을 작업을 하나로 제한하고 나머지는 후속 장부로 분리",
    ),
    "escalating_silence": (
        "재진입 간격이 점점 벌어짐",
        "재진입 직후 계속·분납·탕감 중 하나를 결정하고 결정 없이 닫지 않기",
    ),
    "new_project_nearby": (
        "중단 시점 근처에 다른 프로젝트가 시작됨",
        "새 작업을 열기 전에 현재 항목의 우선순위와 종결 여부를 확인",
    ),
}

FILE_TOKEN = re.compile(
    r"(?<![\w.-])([\w.@+~-]+(?:[/\\][\w.@+~-]+)*\."
    r"(?:py|js|jsx|ts|tsx|json|md|toml|yaml|yml|html|css|sql))(?![\w.-])",
    re.IGNORECASE,
)


def run_read_only(command: list[str], cwd: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10,
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def primary_ref(item: dict) -> dict | None:
    refs = item.get("source_refs") or []
    return refs[0] if refs else None


def inspect_project(item: dict) -> dict:
    """Inspect only small, relevant project metadata; never mutate the project."""
    ref = primary_ref(item)
    project = (ref or {}).get("project_path", "")
    public_demo = ((not ref and item.get("project") == "<anonymized>")
                   or bool(ref and ref.get("runtime") == "demo"))
    snapshot = {
        "read_only": True,
        "project_exists": bool(project and os.path.isdir(project)),
        "project_path": project if project and not public_demo else None,
        "guidance_files": [],
        "manifest_files": [],
        "relevant_files": [],
        "git": {"available": False, "branch": None, "dirty_files": None,
                "recent_commits": []},
        "verification_commands": [],
    }
    if public_demo:
        snapshot["public_demo"] = True
        return snapshot
    if not snapshot["project_exists"]:
        return snapshot

    root = Path(project)
    for name in ("README.md", "README", "AGENTS.md", "CLAUDE.md"):
        if (root / name).is_file():
            snapshot["guidance_files"].append(name)

    for name in ("package.json", "pyproject.toml", "pytest.ini", "Makefile", "Cargo.toml"):
        if (root / name).is_file():
            snapshot["manifest_files"].append(name)

    package_json = root / "package.json"
    if package_json.is_file():
        try:
            scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, ValueError, AttributeError):
            scripts = {}
        for name in ("test", "build", "lint"):
            if name in scripts:
                snapshot["verification_commands"].append(
                    "npm test" if name == "test" else f"npm run {name}"
                )
    if ((root / "pyproject.toml").is_file() or (root / "pytest.ini").is_file()
            or (root / "tests").is_dir()):
        snapshot["verification_commands"].append("python -m pytest")
    if (root / "scripts" / "selftest.py").is_file():
        snapshot["verification_commands"].append("python scripts/selftest.py")
    if (root / "Cargo.toml").is_file():
        snapshot["verification_commands"].append("cargo test")

    last_text = ((item.get("last_words") or {}).get("text") or "")
    for token in FILE_TOKEN.findall(last_text):
        candidate = root / token.replace("\\", os.sep).replace("/", os.sep)
        try:
            candidate.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if candidate.is_file():
            snapshot["relevant_files"].append(token.replace("\\", "/"))

    if (root / ".git").exists():
        code, branch = run_read_only(["git", "branch", "--show-current"], project)
        status_code, status = run_read_only(["git", "status", "--porcelain"], project)
        log_code, log = run_read_only(
            ["git", "log", "-3", "--pretty=format:%h %s"], project
        )
        snapshot["git"] = {
            "available": code == 0 or status_code == 0,
            "branch": branch or None,
            "dirty_files": len(status.splitlines()) if status_code == 0 else None,
            "recent_commits": log.splitlines() if log_code == 0 and log else [],
        }

    snapshot["verification_commands"] = list(dict.fromkeys(
        snapshot["verification_commands"]
    ))[:3]
    return snapshot


def evidence_summary(item: dict) -> str:
    signals = item.get("stall_signals") or []
    if signals:
        return signals[0].get("detail") or signals[0].get("type", "정지 신호")
    words = ((item.get("last_words") or {}).get("text") or "").strip()
    if words:
        return f"마지막 대화: {words[:120]}"
    return "확인 가능한 마지막 대화나 정지 신호가 없음"


def blocker_action(item: dict) -> tuple[str, str, str]:
    types = [s.get("type") for s in item.get("stall_signals", [])]
    if "stalled_at_blocker" in types:
        return ("막힌 단계 분리", "마지막 인증·결제 단계를 최소 조건으로 재현하고 필요한 권한과 설정을 분리한다.",
                "막힘의 재현 조건과 해결에 필요한 입력이 한 목록으로 정리됨")
    if "repeated_rewrite" in types:
        return ("기존 결과 채택 기준 확정", "새로 작성하지 말고 현재 결과 중 유지할 부분과 폐기 기준을 먼저 정한다.",
                "유지할 결과 하나와 폐기 기준이 기록됨")
    if "scope_creep" in types:
        return ("닫을 범위 하나 선택", "열린 작업 중 독립적으로 완료할 수 있는 한 조각만 선택한다.",
                "이번 상환 범위 밖의 작업이 분리되고 한 조각만 남음")
    if "escalating_silence" in types:
        return ("계속할 조건 확인", "마지막 결과가 아직 필요한지 확인하고 계속·분납·탕감 기준을 정한다.",
                "이번 항목의 처리 결정과 근거가 기록됨")
    return ("마지막 질문 해소", "마지막 대화의 열린 질문을 재현 가능한 한 문장으로 바꾸고 답에 필요한 입력을 확인한다.",
            "열린 질문과 필요한 입력이 명시됨")


def contextual_option_copy(item: dict, snapshot: dict) -> dict[str, tuple[str, str, str]]:
    """Turn the last words into concrete, user-facing actions without inventing facts."""
    words = ((item.get("last_words") or {}).get("text") or "").strip()
    lower = words.lower()
    guide = (snapshot.get("guidance_files") or ["프로젝트 안내 문서"])[0]
    verify = (snapshot.get("verification_commands") or [])
    verify_label = f"`{verify[0]}`" if verify else "프로젝트의 기존 검증 절차"

    if any(token in lower for token in ("원격", "다른 pc", "다른 컴퓨터", "github", "깃허브")):
        return {
            "A": ("다른 PC에서 여는 길 확인", "GitHub 연결, 미커밋 파일, 실행 방법을 확인하고 다른 PC에서 이어갈 최소 절차를 정리한다.",
                  "새 폴더에서 저장소를 내려받아 안내된 명령으로 시작할 수 있음"),
            "B": ("원격 작업의 빈칸 채우기", "저장소에 올라가지 않은 파일과 로컬에만 있는 설정을 구분해 원격 작업을 막는 항목만 목록화한다.",
                  "다른 PC에서 빠지는 파일·설정과 옮기는 방법이 한 목록에 정리됨"),
            "C": ("원격 재개 절차 완성", f"{guide}에 설치·실행·검증 순서를 적고 깨끗한 폴더에서 처음부터 따라 해본다.",
                  "새 폴더에서 설치부터 실행·검증까지 안내만 보고 재현됨"),
        }
    if any(token in lower for token in ("사례글", "원고", "초안", "참가한 대회")):
        return {
            "A": ("게시 가능한 초안 만들기", "작성 중인 초안과 참고 페이지를 나란히 열고 반드시 들어갈 사실과 확인이 필요한 내용을 구분한다.",
                  "출처가 필요한 자리와 보완할 사실이 표시된 초안 1개가 완성됨"),
            "B": ("사실과 표현 분리", "대회명·참가 내용·결과처럼 검증할 사실을 출처와 대조하고 과장될 수 있는 문장을 따로 표시한다.",
                  "확인된 사실과 수정할 표현이 구분된 검토 목록이 남음"),
            "C": ("사례글 게시본 완성", "확인된 사실만 반영해 제목·본문·출처 링크를 갖춘 최종 원고를 한 번 소리 내어 검토한다.",
                  "빈칸과 미확인 표현 없이 바로 게시할 최종 원고 1개가 준비됨"),
        }
    if any(token in lower for token in ("sent", "예약목록", "발송", "수신", "성공한")):
        return {
            "A": ("발송 1건의 실제 상태 확인", "가장 최근 발송 1건을 골라 API 응답, 발송 기록, 실제 수신 여부를 차례로 확인한다.",
                  "`sent`가 접수·발송·수신 중 어느 단계인지 증거와 함께 설명할 수 있음"),
            "B": ("상태값의 의미 확정", "코드에서 `sent`가 기록되는 조건과 실패 상태로 바뀌는 조건을 찾아 실제 기록과 대조한다.",
                  "상태값의 생성 조건과 실제 성공을 확인할 추가 증거가 정리됨"),
            "C": ("발송 확인 흐름 종결", "테스트 발송 1건으로 예약 등록부터 상태 변경과 수신 확인까지 전체 흐름을 점검한다.",
                  "테스트 1건의 등록·발송·수신 결과가 한 기록으로 남음"),
        }
    if "claude" in lower and any(token in lower for token in ("실행", "안돼", "안 돼", "문제")):
        return {
            "A": ("실패 원인 한 곳으로 좁히기", "프로젝트 폴더에서 Claude 설치 경로와 버전을 확인하고 실패 명령을 한 번 실행해 첫 오류를 남긴다.",
                  "원인이 설치·경로·권한·실행 환경 중 하나로 좁혀짐"),
            "B": ("실행 환경 충돌 확인", "일반 터미널과 현재 실행 환경의 Claude 경로·버전·환경 차이를 비교한다.",
                  "어느 환경 차이가 실행을 막는지 비교 결과로 확인됨"),
            "C": ("프로젝트에서 재개 성공", "확인된 정상 명령으로 프로젝트를 열고 기존 세션 재개까지 한 번 검증한다.",
                  "프로젝트 폴더에서 Claude가 시작되고 기존 작업을 다시 열 수 있음"),
        }
    if any(token in lower for token in ("자막", ".srt", "srt 파일")):
        return {
            "A": ("첫 1분 자막으로 방식 확인", "전체 영상을 처리하기 전에 첫 1분만 영문 SRT로 만들고 영상에 적용해 타이밍을 확인한다.",
                  "첫 1분 영문 자막의 순서와 타임코드가 영상에 맞음"),
            "B": ("음성·싱크 장애물 제거", "잘 들리지 않는 구간과 자막이 밀리는 지점을 표시하고 처리 기준을 먼저 정한다.",
                  "불명확한 음성과 싱크 보정 기준이 예시 구간과 함께 정리됨"),
            "C": ("영문·한글 SRT 완성", "영문 자막 전체를 검토한 뒤 자연스러운 한글 자막을 만들고 영상에서 처음부터 끝까지 확인한다.",
                  "영문·한글 SRT 두 파일이 끝까지 재생되며 누락 구간이 없음"),
        }
    if "이미지 경로" in lower or ("이미지" in lower and "일괄" in lower):
        return {
            "A": ("이미지 3개로 변환 확인", "대표 이미지 경로 3개만 골라 새 규칙으로 바꾸고 미리보기에서 정상 표시되는지 확인한다.",
                  "서로 다른 형태의 이미지 3개가 새 위치에서 정상 표시됨"),
            "B": ("경로 패턴과 예외 분리", "현재 이미지 경로를 상대·절대·외부 주소로 나누고 일괄 변경에서 제외할 예외를 표시한다.",
                  "변경할 경로 규칙과 건드리지 않을 예외가 한 목록에 정리됨"),
            "C": ("전체 변환 후 게시 준비", "검증한 규칙으로 전체 경로를 바꾸고 깨진 이미지 검색과 게시 전 미리보기를 실행한다.",
                  "깨진 이미지가 없고 게시 전 미리보기에서 핵심 페이지가 정상 표시됨"),
        }
    if any(token in lower for token in ("빌드", "배포 전", "배포 직전", "deploy")):
        return {
            "A": ("첫 빌드 오류 잡기", "현재 빌드를 한 번 실행해 가장 먼저 실패하는 오류와 관련 파일을 기록한다.",
                  "첫 실패 위치와 바로 수정할 대상 1곳이 확인됨"),
            "B": ("정상 결과를 지키며 실패 좁히기", "마지막 정상 빌드에서 유지할 결과를 고정한 뒤 현재 변경과 비교해 실패 범위를 하나로 좁힌다.",
                  "유지할 결과, 재현 명령, 원인 후보 1개가 함께 기록됨"),
            "C": ("빌드부터 배포 직전까지 닫기", f"빌드 오류를 해결한 뒤 {verify_label}와 배포 전 확인 항목을 순서대로 실행한다.",
                  "빌드가 통과하고 남은 배포 차단 요소가 없거나 명시적으로 기록됨"),
        }
    if any(token in lower for token in ("로그인", "세션", "인증")):
        return {
            "A": ("세션이 풀리는 순간 확인", "로그인부터 새로고침까지 가장 짧은 흐름을 한 번 실행하고 세션 값이 사라지는 시점을 기록한다.",
                  "세션이 끊기는 단계와 바로 확인할 저장 위치 1곳이 확인됨"),
            "B": ("저장·복원 조건 비교", "세션을 저장하는 코드와 새로고침 때 복원하는 코드를 나란히 확인해 키·만료·도메인 조건을 비교한다.",
                  "저장과 복원 사이에서 다른 조건이 한 목록으로 정리됨"),
            "C": ("로그인 유지 검증", "수정 후 로그인·새로고침·재접속 흐름을 차례로 실행해 세션 유지 여부를 확인한다.",
                  "새로고침과 재접속 뒤에도 로그인 상태가 유지되거나 남은 실패가 기록됨"),
        }
    if any(token in lower for token in ("차단", "요청 간격", "크롤")):
        return {
            "A": ("요청 1건의 응답 확인", "현재 설정으로 요청 1건만 보내 응답 코드와 재시도 안내 헤더를 기록한다.",
                  "차단 여부와 서버가 요구하는 대기 조건을 증거로 확인함"),
            "B": ("허용 범위 먼저 확정", "대상 서비스의 공개 이용 조건과 현재 요청 빈도를 비교해 허용할 간격과 중단 조건을 정한다.",
                  "준수할 요청 간격·최대 재시도·즉시 중단 조건이 기록됨"),
            "C": ("안전한 수집 흐름 검증", "정한 간격과 중단 조건을 적용한 소량 실행으로 누락·중복·차단 여부를 확인한다.",
                  "소량 실행 결과와 중단 조건이 기록되고 차단 없이 종료됨"),
        }

    target = (snapshot.get("relevant_files") or snapshot.get("manifest_files")
              or snapshot.get("guidance_files") or ["마지막 작업 결과"])[0]
    return {
        "A": ("다음 한 걸음 확정", f"`{target}`와 마지막 대화를 함께 열어 지금 남아 있는 작업을 하나만 표시한다.",
              "다음에 손댈 대상 1곳과 행동 1개가 적혀 있음"),
        "B": ("막힌 질문에 필요한 것 모으기", "마지막 질문에 답하려면 필요한 입력·권한·결정을 확인해 없는 것만 목록화한다.",
              "바로 답할 수 없는 이유와 필요한 입력이 한 목록에 정리됨"),
        "C": ("검증 가능한 결과로 닫기", f"남은 작업을 처리한 뒤 {verify_label}로 결과를 확인하고 후속 작업을 분리한다.",
              "검증 결과가 남고 이번 범위의 미완료 작업이 0개이거나 별도 항목으로 분리됨"),
    }


def build_options(item: dict, snapshot: dict) -> tuple[list[dict], str | None]:
    if item.get("sensitive_topics") and not item.get("sensitive_approved"):
        return [], "사적인 사안입니다. 사용자 승인 후에만 상환안을 생성합니다."

    public_demo = bool(snapshot.get("public_demo"))
    ref = primary_ref(item)
    if not public_demo and (not ref or not snapshot.get("project_exists")):
        return ([{
            "option_id": "A", "strategy": "quick-win", "recommended": True,
            "title": "프로젝트 위치 복구", "first_action": "마지막 대화의 프로젝트가 이동·삭제됐는지 확인하고 현재 위치를 연결한다.",
            "why": "원본 프로젝트 경로를 현재 파일시스템에서 확인할 수 없음",
            "timebox": 30, "done_when": "존재하는 프로젝트 경로 또는 정식 탕감 결정이 확인됨",
            "tradeoff": "코드 작업은 시작하지 않지만 잘못된 경로에서 작업하는 위험을 막음",
        }], "추가 상환안을 만들 프로젝트 근거가 부족합니다.")

    words = ((item.get("last_words") or {}).get("text") or "").strip()
    signals = item.get("stall_signals") or []
    if not words and not signals:
        return ([{
            "option_id": "A", "strategy": "quick-win", "recommended": True,
            "title": "재진입 근거 확인", "first_action": "프로젝트 안내 문서와 최근 변경에서 마지막 작업 지점을 확인한다.",
            "why": "프로젝트는 확인되지만 마지막 대화와 정지 신호가 없음",
            "timebox": 30, "done_when": "중단 지점과 다음 행동을 뒷받침할 근거가 하나 이상 확인됨",
            "tradeoff": "실행보다 근거 복구를 우선해 잘못된 작업 추천을 피함",
        }], "추가 상환안을 만들 대화 근거가 부족합니다.")

    evidence = evidence_summary(item)
    copy = contextual_option_copy(item, snapshot)
    b_title, b_action, b_done = blocker_action(item)
    if copy.get("B"):
        b_title, b_action, b_done = copy["B"]
    ship = any(s.get("type") == "stalled_before_ship" for s in signals)
    recommended = "C" if ship else ("B" if signals else "A")

    options = [
        {
            "option_id": "A", "strategy": "quick-win", "recommended": recommended == "A",
            "title": copy["A"][0], "first_action": copy["A"][1],
            "why": evidence, "timebox": 30,
            "done_when": copy["A"][2],
            "tradeoff": "가장 빨리 진전하지만 전체 완료까지는 후속 상환이 필요할 수 있음",
        },
        {
            "option_id": "B", "strategy": "unblock", "recommended": recommended == "B",
            "title": b_title, "first_action": b_action, "why": evidence,
            "timebox": 60, "done_when": b_done,
            "tradeoff": "당장 결과물은 작아도 같은 장애물에서 다시 멈출 가능성을 줄임",
        },
        {
            "option_id": "C", "strategy": "completion", "recommended": recommended == "C",
            "title": copy["C"][0], "first_action": copy["C"][1], "why": evidence,
            "timebox": 120, "done_when": copy["C"][2],
            "tradeoff": "가장 완결성이 높지만 한 번에 필요한 집중 범위가 큼",
        },
    ]
    return options, None


def self_improvement_loop(item: dict, verification: str) -> dict:
    signals = item.get("stall_signals") or []
    if signals and signals[0].get("type") in SIGNAL_GUARDRAILS:
        observed, guardrail = SIGNAL_GUARDRAILS[signals[0]["type"]]
    else:
        observed = "이번 항목의 마지막 대화에서 작업이 열린 채 종료됨"
        guardrail = "세션을 닫기 전에 다음 행동과 완료 조건을 한 줄로 남기기"
    return {
        "observed_pattern": observed,
        "guardrail": guardrail,
        "checkpoint": "첫 작업 완료 직후와 다음 세션 종료 전",
        "success_signal": verification,
        "review_after": "이번 상환 종료 직후 장부 상태를 repaid·partial·blocked 중 하나로 갱신",
    }


def build_detail(item: dict, option_id: str, mode: str, snapshot: dict) -> dict:
    option = next((o for o in item.get("repayment_options", [])
                   if o.get("option_id") == option_id), None)
    if option is None:
        raise ValueError(f"상환안 {option_id}을 찾을 수 없습니다")

    verification_commands = snapshot.get("verification_commands") or []
    verification = (verification_commands[0] if verification_commands
                    else option["done_when"])
    area = (snapshot.get("relevant_files") or snapshot.get("manifest_files")
            or snapshot.get("guidance_files") or ["프로젝트 루트"])
    tasks = [{
        "files_or_area": area[:3],
        "command_or_action": option["first_action"],
        "done_when": option["done_when"],
    }]
    if mode == "repay" and option["strategy"] != "quick-win":
        tasks.append({
            "files_or_area": (snapshot.get("manifest_files") or ["검증 설정"])[:3],
            "command_or_action": (f"`{verification_commands[0]}`을 실행해 결과를 확인한다."
                                  if verification_commands else
                                  "프로젝트의 기존 테스트·빌드 절차로 결과를 확인한다."),
            "done_when": "통과 결과 또는 재현 가능한 차단 요소가 남음",
        })
    if mode == "repay" and option["strategy"] == "completion":
        tasks.append({
            "files_or_area": ["완료 기준"],
            "command_or_action": "완료 조건과 남은 작업을 대조하고 이번 범위를 종결한다.",
            "done_when": "남은 작업이 없거나 후속 장부로 명시적으로 분리됨",
        })

    stopped = evidence_summary(item)
    plan = {
        "selected_option": option_id,
        "mode": mode,
        "objective": option["title"],
        "stopped_at": stopped,
        "first_action": option["first_action"],
        "tasks": tasks[:1] if mode == "installment" else tasks[:3],
        "blockers_or_decisions": (["프로젝트 위치 확인"] if not snapshot.get("project_exists")
                                  and not snapshot.get("public_demo") else []),
        "timebox": 30 if mode == "installment" else option["timebox"],
        "verification": verification,
        "source_refs": item.get("source_refs") or [],
        "safety_boundary": "사용자 승인 전에는 파일 수정·명령 실행·배포를 하지 않음",
    }
    plan["self_improvement"] = self_improvement_loop(item, verification)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create evidence-grounded Laterbill repayment options (read-only)."
    )
    parser.add_argument("-i", "--input", default="-", help="ledger JSON or '-' for stdin")
    parser.add_argument("-o", "--output", default="-", help="enriched JSON or '-' for stdout")
    parser.add_argument("--item", help="only detail this item_id")
    parser.add_argument("--option", choices=["A", "B", "C"], help="selected repayment option")
    parser.add_argument("--mode", choices=["repay", "installment", "write-off"], default="repay")
    parser.add_argument("--approve-sensitive", action="append", default=[], metavar="ITEM_ID")
    parser.add_argument("--reason", default="사용자가 정식 종결을 선택함")
    args = parser.parse_args()

    if args.input == "-":
        doc = json.load(sys.stdin)
    else:
        with open(args.input, encoding="utf-8-sig") as fh:
            doc = json.load(fh)

    selected_found = not args.item
    for item in doc.get("line_items", []):
        if item.get("item_id") in args.approve_sensitive:
            item["sensitive_approved"] = True
        snapshot = inspect_project(item)
        options, note = build_options(item, snapshot)
        item["repayment_options"] = options
        item["repayment_note"] = note

        if args.item and item.get("item_id") == args.item:
            selected_found = True
            item["project_snapshot"] = snapshot
            if args.mode == "write-off":
                item["settlement_record"] = {
                    "status": "write_off", "reason": args.reason, "tasks": [],
                    "self_improvement": {
                        "observed_pattern": evidence_summary(item),
                        "guardrail": "같은 항목을 다시 열기 전에 탕감 사유와 현재 필요성을 비교",
                        "checkpoint": "다시 시작하려는 시점",
                        "success_signal": "재개 또는 유지할 탕감 결정이 근거와 함께 남음",
                        "review_after": "재개 시 새 항목으로 등록",
                    },
                }
            elif args.option:
                item["repayment_plan"] = build_detail(
                    item, args.option, args.mode, snapshot
                )

    if not selected_found:
        parser.error(f"item_id를 찾을 수 없습니다: {args.item}")
    if args.item and args.mode != "write-off" and not args.option:
        parser.error("상환 또는 분납 상세계획에는 --option A|B|C가 필요합니다")

    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    text = text.encode("utf-8", errors="replace").decode("utf-8")
    if args.output == "-":
        sys.stdout.write(text)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
