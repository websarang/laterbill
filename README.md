# 하다 만 일 종결반 (Laterbill)

로컬 AI 대화에 남은 미완료 업무를 추적하고, 세 가지 실행 가능한 종결안을 제시하는 상환 에이전트입니다.

> 한 일을 칭찬하는 회고 대신, 끝내지 않은 일의 원금·연체·재진입 이자를 계산하고 다시 시작할 세 가지 방법을 제안합니다.

Laterbill은 Claude Code와 Codex의 **로컬 대화 기록**에서 중단된 프로젝트, 답 없이 끝난 요청,
말로 미룬 약속을 찾습니다. 각 항목은 프로젝트 폴더와 마지막 세션으로 돌아갈 좌표를 보존하고,
다음 세 가지 상환안을 만듭니다.

- **A 빠른 진전:** 30분 안에 현재 상태와 다음 행동 하나 확인
- **B 장애물 해소:** 막힌 조건·권한·입력 또는 유지할 기존 결과를 먼저 정리
- **C 완결 우선:** 테스트·빌드·완료 조건까지 확인해 업무 종결

선택한 안은 대상 파일, 실행 행동, 완료 조건을 가진 최대 3개 작업으로 상세화됩니다.
상환 뒤에는 사람의 성격이 아닌 **반복된 작업 흐름**을 개선하는 가드레일까지 남깁니다.

## 30초 데모

Python 3.9 이상만 필요하며 외부 패키지와 네트워크 호출이 없습니다.

```bash
python laterbill/scripts/run.py --demo
python laterbill/scripts/selftest.py
```

채팅에서는 `/laterbill`을 입력하면 수집부터 청구서 발행까지 자동으로 진행됩니다.
먼저 수집 범위만 확인하려면 `/laterbill 수동`을 입력하고, 요약을 확인한 뒤
`청구서 발행` 또는 `발행 취소`를 선택합니다.

실제 로컬 기록으로 실행하려면 `--demo`만 빼면 됩니다.

```bash
python laterbill/scripts/run.py --max-items 10
python laterbill/scripts/run.py --manual --max-items 10
python laterbill/scripts/run.py --format html -o bill.html
```

## 무엇이 다른가

| 일반 회고 | Laterbill |
|---|---|
| 완료한 일을 요약 | 끝내지 않은 일을 감사 |
| 사용자가 기억해 입력 | 이미 쌓인 로컬 대화가 증거 |
| TODO 목록 제시 | 프로젝트·마지막 세션으로 복귀 |
| 다음 행동 하나 | 빠른 진전·장애물 해소·완결 우선 3안 비교 |
| 일회성 조언 | 상환 후 작업 흐름 자가개선 가드레일 |

원금은 투입한 대화 턴 수, 연체는 마지막 활동 이후 경과일, 이자는 하루 이상 침묵 뒤
같은 프로젝트에 재진입한 횟수입니다. 납부 기한은 사용자가 직접 말한 기한이나 관측된
재방문 주기가 있을 때만 냅니다. 근거가 없으면 비웁니다.

## 원본으로 돌아가기

비공개 장부는 런타임, 세션 ID, 프로젝트 경로, 존재 여부와 마지막 활동을 `source_refs`에
보존합니다.

```text
Codex      codex resume -C "<project>" "<session-id>"
Claude     cd "<project>" && claude --resume "<session-id>"
```

프로젝트가 이동되거나 삭제됐으면 잘못된 명령을 만들지 않고 위치 복구안 하나만 제시합니다.
공유용 `--anonymize`에서는 경로·세션·재개 명령·원본 식별자가 모두 제거됩니다.

## 안전 설계

- 기본 동작은 읽기 전용이며 프로젝트를 수정하지 않습니다.
- 장부와 계획은 로컬에서만 처리하며 네트워크 라이브러리를 사용하지 않습니다.
- 이메일·토큰·전화번호·주민번호·홈 경로를 인용 전에 마스킹합니다.
- 건강·가족·금전·고용 관련 원문과 상환안은 해당 항목 승인 전에는 렌더링하지 않습니다.
- `insufficient_data`와 `no_debt`를 정상 결과로 취급하고 없는 빚을 만들지 않습니다.
- “게을러서”, “두려워서”처럼 기록에 없는 동기와 성격을 진단하지 않습니다.
- 60일 이상 방치된 항목은 재개보다 정식 탕감을 우선 권합니다.
- 상세계획을 보여주고 사용자가 승인하기 전에는 파일 수정·명령 실행·배포를 하지 않습니다.

## 설치

진단만 실행하면 아무것도 변경하지 않습니다.

```bash
python laterbill/scripts/install.py
```

사용자 범위의 Claude Code와 Codex에 함께 설치하려면:

```bash
python laterbill/scripts/install.py --install --runtime all
```

Claude Code 프로젝트 범위만 설치하려면:

```bash
python laterbill/scripts/install.py --install --runtime claude-code --scope project
```

## 검증 근거

`python laterbill/scripts/selftest.py`는 최신 Codex envelope와 Claude 형식, 런타임별 파싱 통계,
source_refs, 익명화, 상환안 차별성, 선택안 상세화, 분납, 탕감, 민감정보 승인, 자가개선 루프,
한글 파이프라인, 자동·수동 발행 분리, HTML 주입 차단과 네트워크 부재를 포함한 **34개 검증**을 실행합니다.
`python tools/verify-release.py`는 Skill ZIP을 새로 만들고 임시 폴더에 압축 해제한 뒤 동일 검증을
다시 수행합니다. [실제 검증 로그](docs/assets/proof/release-verification.txt)에는 양쪽 `34/34`,
ZIP SHA-256, 합성 재개 명령, 익명화 결과와 읽기 전용 전후 해시가 기록되어 있습니다.

- [1분 심사 경로](JUDGE_START_HERE.md)
- [Skill 본체](laterbill/SKILL.md)
- [합성 fixture 심사 예시](laterbill/samples/adjudicated-bill.md)
- [현재 소스·새 ZIP 실제 검증 로그](docs/assets/proof/release-verification.txt)
- [공개 데모](https://websarang.github.io/laterbill/)
- [결선 발표 자료](https://websarang.github.io/laterbill/presentation/) · [PNG 10장](docs/assets/presentation/)

AI 반려에이전트 스킬톤 출품작 · 제작자 에이스
