# Claude Code 작업 지침

이 저장소는 반려 에이전트 스킬톤 출품작 `하다 만 일 종결반 (Laterbill)`이다.
Codex와 Claude Code 어느 쪽에서 열더라도 먼저 다음 문서를 읽는다.

1. `JUDGE_START_HERE.md`
2. `laterbill/SKILL.md`
3. `submission/SUBMISSION.md`
4. `docs/assets/proof/release-verification.txt`

## 현재 구현 상태

- 한글명은 `하다 만 일 종결반`, 영문명은 `Laterbill`로 확정했다.
- 공식 설명은 `로컬 AI 대화에 남은 미완료 업무를 추적하고, 세 가지 실행 가능한 종결안을 제시하는 상환 에이전트`다.
- 최신 Codex envelope와 Claude Code 로컬 기록 파서가 구현되어 있다.
- 각 청구는 private `source_refs`로 프로젝트·세션에 연결된다.
- 가능한 경우 A 빠른 진전, B 장애물 해소, C 완결 우선의 서로 다른 상환안 3개를 낸다.
- 선택안만 최대 3개 작업으로 상세화하며 분납은 1작업, 탕감은 0작업이다.
- 상세계획에는 작업 흐름을 바꾸는 자가개선 루프가 포함된다.
- 민감 원문은 항목별 승인 전에는 렌더링되지 않는다.
- 공개 익명화는 경로, 세션 ID, 원본 좌표와 재개 명령을 제거한다.
- 사용자 승인 전 프로젝트 점검은 읽기 전용이다.

## 검증된 릴리스

- 명령: `python tools/verify-release.py`
- 현재 소스: `33/33 통과`
- 새 ZIP 압축 해제본: `33/33 통과`
- ZIP: `laterbill-skill.zip`, 13 files, 67,311 bytes
- SHA-256: `3ae0173d16f34e8041cc0ff6d5df44ee9a06b475962fceb856bc7d38914ebb3f`
- 공개 증거: `docs/assets/proof/release-verification.txt`
- 이미지: `docs/assets/evidence/evidence-1.webp`부터 `evidence-5.webp`

검증기 실행 후 ZIP 크기나 해시가 달라지면 이 문서와 제출 원고의 값을 함께 갱신한다.

## 제출 결정

- 2026-08-15T14:54:25+09:00 사용자가 추가 기능 보완을 멈추고 현재 검증본을 제출하기로 결정했다.
- 제출 후보는 위 SHA-256의 `laterbill-skill.zip`이다.
- 제출 직전에는 기능을 더 수정하지 않는다. 불가피하게 파일이 바뀌면 `python tools/verify-release.py`를 다시 실행하고 ZIP 크기·해시·증거 로그를 함께 갱신한다.

## 공개 대상

- 저장소: <https://github.com/websarang/laterbill>
- 데모: <https://websarang.github.io/laterbill/>
- 제출 원고: `submission/SUBMISSION.md`
- 제출 ZIP: `laterbill-skill.zip`

## 남은 외부 단계

1. 공개 저장소 `main`에 push하고 GitHub Pages를 `/docs`로 활성화한다.
2. 로그아웃 상태에서 저장소·Pages·proof 로그를 확인한다.
3. 제출 화면에 본문, 링크 2개, WebP 5장, ZIP을 올린다.
4. 전화번호, PIN, 동의는 사용자가 직접 입력한다.
5. 제출번호, 상태, 업로드 시각, ZIP 크기와 잠금 상태를 이 문서와 인수인계 문서에 기록한다.

## 작업 경계

- `.omc/`, `.omx/`, `omx_wiki/`, `__pycache__/`, `*.pyc`, 실제 대화 기록을 공개 커밋이나 ZIP에 넣지 않는다.
- 공개 자료는 합성 fixture와 익명화 결과만 사용한다.
- 근거 없는 성능·호환성·수상 보장을 추가하지 않는다.
- 사용자 승인 전 파일 수정, 배포 같은 상환 실행을 하지 않는다.
