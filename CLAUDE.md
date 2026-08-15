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
- 현재 소스: `35/35 통과`
- 새 ZIP 압축 해제본: `35/35 통과`
- ZIP: `laterbill-skill.zip`, 13 files, 72,873 bytes
- SHA-256: `485cd46183cb160b322d2b247ec85eafc31dcc541616071f230159506292af6a`
- 공개 증거: `docs/assets/proof/release-verification.txt`
- 이미지: `docs/assets/evidence/evidence-1.webp`부터 `evidence-5.webp`
- 결선 발표: `docs/presentation/index.html` · 10장 · 1920×1080 PNG는 `docs/assets/presentation/`
- 실제 합성 Skill 실행 화면: `docs/presentation/actual-demo.html`
- 발표 브랜드 에셋: `docs/assets/presentation/ace-coach.png` · 에이스 / 최학곤 배지
- 독립 심사: 45/50, 47/50 · 평균 92/100 · 치명적 결함 0 · 필수 수정 0
- 심사 감사 기록: `.omx/artifacts/ask-codex-laterbill-judge-20260815.md`

검증기 실행 후 ZIP 크기나 해시가 달라지면 이 문서와 제출 원고의 값을 함께 갱신한다.

## 제출 결정

- 2026-08-15T14:54:25+09:00 사용자가 추가 기능 보완을 멈추고 현재 검증본을 제출하기로 결정했다.
- 제출 후보는 위 SHA-256의 `laterbill-skill.zip`이다.
- 제출 직전에는 기능을 더 수정하지 않는다. 불가피하게 파일이 바뀌면 `python tools/verify-release.py`를 다시 실행하고 ZIP 크기·해시·증거 로그를 함께 갱신한다.

## 공개 대상

- 저장소: <https://github.com/websarang/laterbill>
- 데모: <https://websarang.github.io/laterbill/>
- 결선 발표: <https://websarang.github.io/laterbill/presentation/>
- 제출 원고: `submission/SUBMISSION.md`
- 제출 ZIP: `laterbill-skill.zip`

## 남은 외부 단계

1. `main` push와 GitHub Pages 공개는 완료했다. 최종 해시 갱신 커밋도 push한다.
2. 로그아웃 상태에서 저장소·Pages·proof 로그를 확인했다.
3. 제출 화면에 `laterbill-skill.zip`, 제출 본문과 HTTPS 링크 2개를 올린다. 공식 화면은 이미지·대체 텍스트를 받지 않는다.
4. 전화번호, PIN, 동의는 사용자가 직접 입력한다.
5. 제출번호, 상태, 업로드 시각, ZIP 크기와 잠금 상태를 이 문서와 인수인계 문서에 기록한다.

## 작업 경계

- `.omc/`, `.omx/`, `omx_wiki/`, `__pycache__/`, `*.pyc`, 실제 대화 기록을 공개 커밋이나 ZIP에 넣지 않는다.
- 공개 자료는 합성 fixture와 익명화 결과만 사용한다.
- 근거 없는 성능·호환성·수상 보장을 추가하지 않는다.
- 사용자 승인 전 파일 수정, 배포 같은 상환 실행을 하지 않는다.
- 발표 자료를 수정하면 `powershell -ExecutionPolicy Bypass -File tools/capture-presentation.ps1`로 PNG 10장을 다시 만들고 `python tools/verify-presentation.py`, `python tools/verify-presentation-visual.py`, `node tools/verify-presentation-navigation.mjs`를 실행한다. 마지막 명령에는 번들 Node 모듈 경로를 `RUNTIME_NODE_MODULES`로 지정한다.
- 발표 자료는 2026-08-15 사용자 승인에 따라 GitHub `main` 공개 대상에 포함했다.
