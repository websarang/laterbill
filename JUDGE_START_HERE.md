# 하다 만 일 종결반 (Laterbill) — 1분 검증 경로

로컬 AI 대화에 남은 미완료 업무를 추적하고, 세 가지 실행 가능한 종결안을 제시하는 상환 에이전트입니다.

## 30초: 합성 데모

```bash
python laterbill/scripts/run.py --demo --max-items 3
```

각 청구 항목 아래에 서로 다른 A·B·C안이 표시됩니다. 인증 단계에서 멈춘 항목은
`B 장애물 해소`, 배포 직전 항목은 `C 완결 우선`이 추천됩니다.

## 20초: 주장 전체 검증

```bash
python laterbill/scripts/selftest.py
python tools/verify-release.py
```

33/33 PASS가 정상입니다. 최신 Codex `session_meta → turn_context → response_item` 파싱,
Claude 형식, 프로젝트·세션 복귀 좌표, 세 가지 안의 차별성, 분납·탕감, 민감 원문 기본 숨김,
자가개선 가드레일과 프로젝트 무변경을 실제 코드로 검사합니다.
두 번째 명령은 새 제출 ZIP을 임시 폴더에 풀고 동일 테스트를 다시 실행합니다.
[실제 검증 로그](docs/assets/proof/release-verification.txt)에서 양쪽 결과와 SHA-256을 확인할 수 있습니다.

### 최종 릴리스 증빙

| 항목 | 검증값 |
|---|---|
| 제출 ZIP | `laterbill-skill.zip` |
| 파일·크기 | 13 files · 67,311 bytes |
| SHA-256 | `3ae0173d16f34e8041cc0ff6d5df44ee9a06b475962fceb856bc7d38914ebb3f` |
| 현재 소스 | 33/33 통과 |
| 새 압축 해제본 | 33/33 통과 |
| 공개 입력 | 합성 fixture, 개인 기록 0건 |
| 복귀 출력 | Codex·Claude 합성 세션 명령 생성 확인 |
| 공유 출력 | `source_refs=[]`, `project=<anonymized>` |
| 읽기 전용 | 점검 전후 README SHA-256 동일 |

모든 공개 텍스트는 strict UTF-8 디코드를 통과합니다. Windows PowerShell 5에서는 BOM 없는 UTF-8
Skill 파일을 `Get-Content -Encoding UTF8 laterbill/SKILL.md`로 읽습니다. `SKILL.md`는 공식 validator가
첫 바이트의 `---`를 검사하므로 BOM 없이 유지하며, 이 조건도 proof 로그에 기록합니다.

## 10초: 증거가 없을 때

```bash
python laterbill/scripts/run.py --sessions-root ./laterbill/fixtures/empty
```

`insufficient_data`와 함께 발행을 거부합니다. 없는 빚을 지어내지 않는 것도 기능입니다.

## 평가기준 대응

| 기준 | 확인할 증거 |
|---|---|
| 기상천외함 | 미완료 업무를 원금·연체·재진입 이자로 회계 처리합니다. 특히 이자는 같은 프로젝트를 다시 열며 맥락을 재구축한 실측 비용입니다. |
| 유용함 | 사용자가 TODO를 미리 적을 필요가 없습니다. 프로젝트 폴더·마지막 세션·첫 행동으로 바로 돌아갑니다. |
| 완성도 | 수집 → 심사 → A·B·C 상환안 → 선택안 상세계획 → 실행 승인 → 결과 기록 → 자가개선 루프가 하나의 흐름입니다. |
| 재사용성 | Claude Code와 최신 Codex JSONL, Windows/POSIX 경로, 사용자 지정 `--sessions-root`를 지원하며 표준 라이브러리만 사용합니다. |
| 신뢰성 | 읽기 전용·로컬 전용, 근거 부족 시 발행 거부, 민감 원문 승인 전 숨김, 익명화, 동기 진단 금지를 33개 테스트로 고정했습니다. |

## 설계에서 일부러 하지 않은 것

- 모든 항목에 억지로 세 안을 만들지 않습니다. 프로젝트나 대화 근거가 없으면 위치 복구안만 냅니다.
- 마음을 추측하지 않습니다. “배포 이야기 중 기록이 끊김”까지만 말하고 이유는 만들지 않습니다.
- 60일 넘은 항목을 무조건 되살리지 않습니다. 탕감은 실패가 아니라 정식 종결입니다.
- 계획 생성과 실행을 분리합니다. 사용자 승인 전에는 파일 수정·명령 실행·배포가 없습니다.

공개 데모: <https://websarang.github.io/laterbill/>  
소스: <https://github.com/websarang/laterbill>
