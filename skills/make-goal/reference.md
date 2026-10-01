# make-goal 참고서 — 판정할 수 있는 goal 을 쓰는 법

사람과 에이전트가 함께 읽는 goal 작성 기준이다. 근거는 2026-09-30 연구다. Claude Code 2.1.285 와 Codex CLI 0.145.0 설치본에서 직접 확인한 값과 공식 문서를 썼고, 출처는 12절에 모았다. SKILL.md 의 절차는 이 문서의 규칙을 따른다.

## 0. 한눈에

1. 길이 제한은 **Claude Code `/goal` 과 Codex goal objective 모두 4,000자**다. 5,000자는 OpenChamber 의 제한이다.
2. 완료를 판정하는 주체가 제품마다 반대다. Claude Code 는 **도구 없는 별도 판정자(Haiku)가 transcript 만** 보고 판정한다. Codex 는 **작업 모델이 스스로** worktree 를 조사해 판정한다.
3. 좋은 goal 은 **끝난 상태 + 확인 명령과 기대값 + 게이밍 차단 제약 + 막힘·중단 규칙** 을 갖춘 짧은 계약문이다. Claude 용이면 "완료를 주장하는 턴에 증거를 새로, 짧게, 원문 그대로 출력한다" 를 반드시 더한다.
4. 권장 길이는 3,500자 이하다. 앞 500자 안에 `[목표]` 와 `[완료 조건]` 머리를 둔다.

## 1. 제품별 메커니즘과 길이 제한

### 1.1 길이 제한

| 제품 · 경로 | 제한 | 세는 방식 | 비고 |
| --- | --- | --- | --- |
| Claude Code `/goal <조건>` | **4,000** | trim 뒤 JS `length` (UTF-16 code unit) | 넘으면 `Goal condition is limited to 4000 characters (got N)`. 첫 릴리스 2.1.139 부터 같다 |
| Claude Code ProposeGoal (모델이 제안하는 goal) | 500 | 표시용 길이 | 사용자가 승인 창에서 전부 읽을 수 있어야 해서 |
| Claude Code 판정 피드백에 다시 인용되는 조건 | 500 | — | 같은 조건이 이미 transcript 에 있으면 500자로 잘라 인용한다 |
| Codex `thread/goal/set` objective | **4,000** | Rust `chars().count()` (Unicode scalar) | 서버 쪽 제한이라 모든 클라이언트에 적용된다. 0.128.0 부터 같다 |
| Codex TUI `/goal` 입력 | 사실상 무제한 | 4,000자를 넘으면 파일로 뺀다 | 0.140.0 이상. objective 에는 `Read the Codex goal objective file at <path> before continuing.` 한 줄만 남는다 |
| OpenChamber session goal | **5,000** | — | "5,000자" 의 출처로 가장 유력하다. 판정자(small model)는 objective 와 마지막 응답만 본다 |
| Qwen Code `/goal` | 4,000 | — | 커뮤니티 이슈 기준 |

- 한글 음절은 두 제품 모두 1자다. 이모지는 Claude 에서 2자, Codex 에서 1자다. `scripts/check_goal.py` 가 제품별로 센다.
- Codex continuation 은 자동 턴마다 objective 전문을 다시 넣는다. objective 가 길면 턴마다 토큰을 쓴다.

### 1.2 Claude Code `/goal` — 분리된 판정자

- `/goal <조건>` 은 세션 범위 Stop hook(`type: prompt`)을 등록하고 바로 한 턴을 시작한다. 작업 모델에는 "조건 자체를 지시문으로 삼고 사용자에게 묻지 말라" 는 kickoff 가 붙는다. **조건문은 작업 모델의 지시문이면서 판정자의 기준이다.**
- 턴이 끝날 때마다 판정자가 `{ok, reason, impossible?}` 를 낸다. 판정자는 기본으로 small fast model(Haiku)이고, 추론이 꺼져 있고, **도구가 없다**(`tools: []`). 타임아웃은 30초다. system prompt 는 "transcript 에 명확한 증거가 없으면 `insufficient evidence` 로 ok:false" 를 요구한다.
- 판정자가 보는 transcript 에는 한계가 있다.
  - 앞부분이 잘린다. 뒤쪽 약 100k 토큰(판정자 컨텍스트의 50%)만 남는다.
  - 큰 tool 출력은 앞 2,000바이트 미리보기만 남는다. 테스트 러너는 요약 줄을 맨 끝에 찍는 경우가 많아서 요약이 안 보일 수 있다.
  - compaction 뒤에는 요약만 남는다. 초반에 남긴 증거는 사라질 수 있다.
  - 파일, 커버리지 리포트, 브라우저, PR 상태는 **출력돼야만** 증거가 된다.
- 미충족이면 `Stop hook feedback: [<조건>]: <reason>` 을 넣고 계속한다. 작업 모델이 도구를 쓰지 않고 Stop 과 차단을 8번 연속 반복하면 "Goal paused" 로 멈춘다. impossible 이면 failed 로 해제된다.
- 백그라운드 작업(subagent, background shell)이 도는 동안에는 평가를 미룬다.
- **대화형 모드에는 턴·토큰 예산이 없다.** 공식 문서도 조건 안에 "or stop after 20 turns" 같은 절을 넣으라고 권한다. headless(`claude -p "/goal …"`)에서만 `--max-turns`, `--max-budget-usd` 를 건다.
- goal 은 권한 모드를 바꾸지 않는다. Manual 모드에서는 허용되지 않은 도구 호출마다 멈춘다.
- trusted workspace 가 아니거나 `disableAllHooks` / `allowManagedHooksOnly` 가 켜져 있으면 쓸 수 없다.
- `/goal` 만 치면 상태를 보여 준다. `/goal clear` 로 해제한다. resume 하면 goal 은 복원되지만 턴 수는 초기화된다.

### 1.3 Codex `/goal` — 작업 모델의 자기 감사

- objective 를 thread goal(active)로 저장하고, thread 가 idle 이 될 때마다 continuation 프롬프트를 넣어 다음 턴을 시작한다. **별도 판정자는 없다.**
- 작업 모델이 모든 도구를 쓰며 completion audit 를 하고 `update_goal(status="complete")` 를 부른다. 지침의 요지는 다음과 같다.
  - 요구사항마다 authoritative evidence 를 찾는다.
  - 불확실하면 미달성으로 본다.
  - 감사는 남은 일을 못 찾는 것으로 끝나지 않고 완료를 증명해야 한다.
- 그래서 **objective 의 번호 항목, 명령, 산출물이 그대로 감사 체크리스트가 된다.** 참조한 파일(PLAN.md 등)도 읽는다.
- `blocked` 는 같은 blocker 가 **3턴 연속** 반복될 때만 쓴다. 지침에 "멈추는 것은 완료가 아니다" 라는 규칙이 있어 **"N턴 뒤 멈춰라" 절과 충돌한다.** 예산은 token budget(소프트 상한)으로 건다.
- objective 는 "untrusted data" 로 취급된다. 금지 사항을 objective 에만 쓰면 보안 경계가 되지 않는다. 강제할 규칙은 sandbox, approval, AGENTS.md 에 둔다.
- TUI `/goal <objective>` 는 예산 없이 시작한다. 예산을 걸려면 대화로 "이 objective 로 goal 을 만들고 token budget 은 N" 이라고 명시하거나, app-server `thread/goal/set` 의 `tokenBudget` 을 쓴다. 모델이 요청받지 않은 예산을 스스로 걸어 작업이 끊긴 사례가 있다.
- 커뮤니티 경험치는 작은 수정 100k–500k, 여러 파일 리팩터 500k–2M, 대형 마이그레이션 2M–10M 토큰이다.
- Plan 모드 턴은 goal 진행으로 치지 않는다. `/plan` 으로 다듬은 뒤 `/goal` 을 거는 흐름을 권한다.

### 1.4 비교와 작성상 함의

| 관점 | Claude Code | Codex | 작성 규칙 |
| --- | --- | --- | --- |
| 판정자 | 분리된 Haiku, 추론 끔 | 작업 모델 자신 | Claude: 판정자가 대조만 하면 되는 답안지를 만들게 한다. Codex: 감사할 수 있는 요구사항 목록을 준다 |
| 보는 것 | transcript 뒤쪽 약 100k 토큰, 큰 출력은 앞 2KB | worktree, 명령, 파일 전체 | Claude: 마지막 턴에 증거를 짧게 다시 출력하게 한다 |
| 파일 참조 | 못 읽는다 | 읽는다 | Claude: 판정 기준을 본문에 인라인한다 |
| 반복 | Stop 마다 평가하고 feedback 을 넣는다 | idle 마다 continuation 을 넣는다 | 둘 다 조건이 매 턴 다시 읽힌다. 짧게, 앞쪽에 무게를 둔다 |
| 끝나는 경로 | met / impossible / 복구 불가 오류 / clear | complete / blocked(3턴) / budget / usage / 턴 오류 | Claude: BLOCKED·STOPPED 종료 절. Codex: 예산 |
| 예산 | 대화형은 없다(`-p` 에서만) | token budget(소프트) | Claude: 턴 절. Codex: tokenBudget |
| 되묻기 | 금지 ("do not pause to ask") | blocked 3턴 규칙 | 회색지대 기본값과 기록 위치를 준다 |

## 2. 원칙 P1–P15

각 원칙은 "규칙 — 왜" 순서다.

- **P1. 활동이 아니라 끝난 상태를 쓴다.** `[목표]` 는 "…가 …인 상태" 한 문장이고 대상 경로·모듈·이슈를 포함한다. "고쳐줘", "추가해" 에는 판정할 상태가 없다.
- **P2. 완료 조건은 "관찰 가능한 상태 — 확인: `명령` → 기대값" 세 요소로 쓴다.** 기대값은 `EXIT=0`, `0 failed`, `→ 0`, `Lines ≥ 85%` 처럼 비교할 수 있는 값이다. "통과한다" 로 끝내지 않는다. 항목은 3–7개다. 추론 없이 판정하는 Haiku 에게 항목이 많으면 오판이 는다.
- **P3. 증거 계약: 완료를 주장하는 턴에서, 새로, 짧게, 원문 그대로.** 판정자 창은 뒤쪽 약 100k 토큰이고, 큰 출력은 앞 2KB 만 남는다.
  - 확인 명령을 다시 실행하게 한다.
  - 출력은 `2>&1 | tail -n 20` 으로 요약 줄만 남긴다.
  - exit code 를 명시적으로 찍는다. Git Bash 는 `; echo "EXIT=${PIPESTATUS[0]}"`, PowerShell 은 `; "EXIT=$LASTEXITCODE"` 다. Claude Bash 도구는 실패할 때만 exit code 를 보여 준다.
  - 개수는 `grep -c`, `wc -l` 로 숫자 하나로 만든다.
  - 최종 메시지에 `C1 ✅ <근거 원문 한 줄>` 체크리스트를 쓰게 한다.
- **P4. (Claude) 판정자는 파일을 못 읽는다.** 판정 기준은 본문에 인라인한다. 파일 산출물은 `grep -n '^## '`, 검사 스크립트의 `rows=… missing=0`, `sed -n '/^## 요약/,/^## /p'` 처럼 출력으로 확인하게 한다.
- **P5. 게이밍을 막는 제약을 쓰고, 제약에도 확인 명령을 붙인다.** exit code 0 만 보상하면 가장 싼 해법은 skip, 느슨한 matcher, golden 재작성, 임계값 하향, ignore 주석이다. "(위반하면 미완료)" 로 판정 기준에 묶는다. 유형별 목록은 6절.
- **P6. 사소하게 참이 되는 조건을 막는다.** `pnpm test` exits 0 은 테스트 0개, 좁은 부분 집합으로도 참이다. 전체 명령을 그대로 쓰고, 최소량(PASSED ≥ 5, rows ≥ 6)을 두고, 시작 시 기준선을 남겨 종료 시 비교하게 한다.
- **P7. 판정할 수 없는 표현을 쓰지 않는다.** 대상은 주관 형용사(깔끔, 잘, 충분히, 최적, production-ready), 출력 없이 요구하는 상태, 사람의 행동이나 외부 이벤트(승인, 머지, 배포 후 에러 없음), 미래 시점이다. 판정자는 not met 을 반복하다 8회 상한에 걸리거나 impossible 로 해제한다. 에이전트가 스스로 만들 수 있는 증거로 바꾼다. 예: "PR 생성 + `gh pr checks <n>` 전부 pass", "`git status` clean".
- **P8. 절대로 참이 될 수 없는 조건을 쓰지 않는다.** 무한 범위("모든 버그"), 모순된 제약, 샌드박스에서 막힌 자원이 필수인 경우다. 도달할 수 있는 상한과 대체 경로를 적는다. 예: "접근 불가면 `미확인` 으로 두고 계속".
- **P9. 되묻지 말고 진행하게 한다.** Claude kickoff 는 묻지 말라고 지시하고, Codex 는 blocked 를 3턴 규칙으로 막는다. "명세에 없는 결정은 X 로 하고 최종 메시지의 '결정 기록' 에 남긴다" 처럼 기본값과 기록 위치를 준다.
- **P10. 종료 경로를 명시한다.**
  - Claude: `GOAL-STATUS: BLOCKED — <원인>` 을 엄격하게 정의한다(같은 원인으로 3번 연속 실패, 시도한 명령과 에러 기록). 턴 상한은 매 턴 `GOAL-TURN k/N` 을 찍게 하고 N턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>` 이다. 둘 다 UI 에는 achieved 로 남으니 최종 줄로 성공과 중단을 가른다.
  - Codex: 턴 상한 대신 token budget 을 쓴다. blocked 는 3턴 규칙에 맞춘다.
  - headless Claude 는 `--max-turns`, `--max-budget-usd` 를 함께 건다.
- **P11. goal 하나에 결과 하나.** "인증 재설계 + OAuth + 문서" 처럼 섞이면 판정과 감사가 모두 흐려진다. 순차 goal 로 나누거나, C 항목을 체크포인트로 두고 명세의 진행 표를 갱신하게 한다.
- **P12. 길이는 하드 4,000, 권장 3,500 이하, 핵심은 앞 500자.** 피드백 인용은 500자에서 잘리고, Anthropic 의 자체 제안 goal 도 500자 이하이고, Codex 는 매 턴 전문을 넣는다. 차기 Codex Guardian 은 JSON 700바이트(한글 약 230자)를 넘는 objective 를 승인 근거에서 통째로 뺀다.
- **P13. 긴 명세는 파일로 보내고, 판정 기준은 goal 본문에 둔다.** 런처 + 명세 패턴(5절).
- **P14. 실행 환경은 goal 밖에서 준비한다.**
  - 권한: auto mode 를 쓰거나 확인 명령을 allowlist 에 넣는다.
  - 긴 테스트는 foreground 로 돌린다. 백그라운드 작업이 있으면 평가가 미뤄진다.
  - Codex sandbox 는 네트워크가 막혀 있다고 가정한다.
  - push, 배포, 삭제 같은 위험 작업은 settings deny 와 sandbox 로 막는다. goal 문구는 판정 기준일 뿐 권한 경계가 아니다.
- **P15. 판정 대상이 아닌 문장은 라벨을 붙여 짧게 둔다.** Claude 판정자는 조건 전체를 Condition 으로 읽는다. 배경은 `[참고] (판정 대상 아님)` 에 경로만 둔다. 절차 지시("TDD 로")는 확인 가능한 조건으로 바꾼다. 예: "재현 테스트가 수정 전에 실패한 출력 인용".

## 3. 템플릿

`{…}` 는 goal 을 쓰는 사람이 채울 자리다. 남아 있으면 `check_goal.py` 가 오류를 낸다. `<…>` 는 작업 모델이 실행 중에 채울 자리다(`<원인>`, `<남은 일>`, `<근거 원문 한 줄>`).

### 3.1 골격 (Claude Code 기준, 공통 코어)

```text
[목표] {끝난 상태 한 문장 — 대상 경로/모듈/이슈 포함}
[완료 조건] 아래 C1–C{n}이 모두 참일 때만 완료로 본다.
C1. {관찰 가능한 상태} — 확인: `{명령} 2>&1 | tail -n 20; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`
C2. {…} — 확인: `{명령}` → {기대값: 0건 / ≥ N / 문자열}
…(3–7개)
[증거 규칙] 완료를 주장하는 턴에서 C1–C{n} 확인 명령을 다시 실행해 출력이 tool 결과에 그대로 남게 한다. 긴 출력은 tail 로 줄인다. 최종 메시지에 `C1 ✅ <근거 원문 한 줄>` 체크리스트를 쓴다. 이전 턴의 기억·요약은 증거가 아니다.
[제약] (위반하면 미완료) {수정 금지 경로}, {테스트·스냅샷·임계값·lint 설정 약화 금지}, {의존성/스키마/API 계약 변경 금지}. 확인: `git diff --stat -- {보호 경로}` 출력이 비어 있음.
[범위 밖] {하지 않을 일}
[막힘·중단] 사용자에게 묻지 않는다. 명세에 없는 결정은 {기본값}으로 하고 {기록 위치}에 남긴다. 같은 원인으로 3번 연속 실패하면 시도한 명령과 에러를 적고 `GOAL-STATUS: BLOCKED — <원인>`. 턴마다 마지막 줄에 `GOAL-TURN k/{N}`, {N}턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>`. 둘 다 종료로 인정한다.
[참고] (판정 대상 아님) 명세: {경로}. 관련 파일: {…}
```

### 3.2 최소형 (ProposeGoal 수준, 500자 이하)

`[목표]` + C 하나 + 핵심 제약 한 줄 + STOPPED 절만 남긴다. 사람이 손으로 짧게 쓸 때 쓴다. `check_goal.py` 는 전체 골격을 요구하므로 이 형태에는 섹션 누락 오류를 낸다.

```text
src/auth 테스트 전부 통과: 마지막 턴에 `pnpm vitest run src/auth 2>&1 | tail -n 5; echo "EXIT=${PIPESTATUS[0]}"` 출력이 EXIT=0.
테스트·설정 파일 수정 금지(`git status --porcelain -- '*.test.ts' vitest.config.ts` 빈 출력).
15턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>` 출력(종료로 인정).
```

### 3.3 섹션별 길이 예산

| 섹션 | 필수 | 권장 길이 | 메모 |
| --- | --- | --- | --- |
| `[목표]` | 필수 | 60–150자 | 앞 500자 안에 `[목표]` 와 `[완료 조건]` 첫 줄 |
| `[완료 조건]` C1–Cn | 필수 | 항목당 80–220자, 3–7개 (합계 600–1,400자) | 항목마다 "상태 — 확인: `명령` → 기대값" |
| `[증거 규칙]` | Claude 필수, Codex 는 `[보고]` 로 | 150–350자 | 재실행, tail, EXIT, 체크리스트 |
| `[제약]` | 필수 | 200–600자 | 보호 경로와 확인 명령 |
| `[범위 밖]` | 선택 | ≤ 250자 | scope creep 방지 |
| `[막힘·중단]` | 필수 | 200–450자 | 기본값, 기록 위치, BLOCKED/STOPPED (Codex 는 blocked 3턴 규칙) |
| `[참고]` | 선택 | ≤ 400자 | "판정 대상 아님", 명세 경로 |
| **합계** | | **≤ 3,500자** (하드 4,000) | examples.md 의 예시는 900–1,450자 |

`check_goal.py` 는 섹션별 길이를 함께 찍는다. 어디를 줄일지 고를 때 이 표와 비교한다.

## 4. 제품별 조정

| 항목 | Claude Code | Codex |
| --- | --- | --- |
| 판정 기준 위치 | 본문에 인라인 (판정자는 파일을 못 읽는다) | 본문 + 정본 파일 참조 가능 ("먼저 읽고 체크리스트 갱신") |
| 증거 | `[증거 규칙]` 필수: 마지막 턴 재실행, 짧은 원문 출력, 체크리스트 | `[보고]`: 완료 시 C 항목마다 증명 명령과 출력 한 줄 (사람이 리뷰하기 위함) |
| `[완료 조건]` 머리 | "아래 C1–Cn 이 모두 참일 때만 완료로 본다" | "현재 worktree 기준으로 모두 참일 때만 update_goal complete:" |
| 종료 절 | `GOAL-STATUS: BLOCKED/STOPPED` + `GOAL-TURN k/N` | 턴 상한 절을 넣지 않는다. blocked 는 "같은 원인으로 3턴 연속 진전이 없을 때만" |
| exit code 관용구 | Bash 도구(Windows 는 Git Bash): `echo "EXIT=${PIPESTATUS[0]}"`. PowerShell 도구면 `"EXIT=$LASTEXITCODE"` | 도구 결과에 exit code 가 들어 있어 생략해도 된다. Windows 셸은 PowerShell 이 기본이다 |
| 예산 | 대화형은 턴 절. `-p` 면 `--max-turns`·`--max-budget-usd` | token budget. goal 밖에서, 사용자가 명시적으로 요청할 때만 |
| 시작 방식 | `/goal <조건>` 을 치면 바로 착수한다. 긴 배경은 먼저 일반 메시지로 주고 이어서 `/goal` (2단계) | 필요하면 `/plan` 으로 다듬은 뒤 `/goal`. 고칠 때는 `/goal edit` |

Codex 꼬리 (공통 코어의 `[목표]`, C 항목, `[제약]` 은 그대로 두고 아래만 바꾼다):

```text
[완료 조건] 현재 worktree 기준으로 모두 참일 때만 update_goal complete:
…C 항목은 Claude 판과 같게…
[막힘·중단] 명세에 없는 결정은 {기본값}으로 하고 {기록 위치}에 남긴다. 같은 원인으로 3턴 연속 진전이 없을 때만 blocked.
[보고] 완료 시 C1–C{n} 각각을 증명하는 명령과 출력 한 줄을 적는다.
```

- PowerShell 로 도는 Codex 에서는 `tail -n 20` 대신 `| Select-Object -Last 20` 을 쓴다.
- `both` 면 공통 코어를 한 번 쓰고 꼬리만 바꾼 두 벌을 낸다. 두 벌 모두 따로 검사한다 (`--target claude`, `--target codex`).

## 5. 런처 + 명세 패턴

요구사항이 많아 압축 사다리(7절)를 다 써도 4,000자를 넘을 때 쓴다. 인벤토리(항목별 목록, 파일별 작업)가 있는 요청이면 처음부터 이 패턴을 고려한다.

- **명세 파일**: 프로젝트 안에 둔다. Codex 가 읽을 수 있고 사람이 리뷰할 수 있어야 한다.
  - 보고서 폴더 규칙이 있으면 그것을 따른다 (예: CLAUDE.md 의 report 규칙).
  - 없으면 `docs/goals/YYYY-MM-DD-<slug>.md` 에 둔다.
  - 명세는 작업 중에 갱신된다. 보호 경로 검사(`git status --porcelain` 등)에서 명세 경로를 뺀다 (`':!docs/goals/…'`).
- **런처** (≤ 3,500자 목표): `[목표]`, `[완료 조건]`, `[증거 규칙]`, `[제약]`, `[막힘·중단]` 을 모두 인라인으로 둔다. Claude 판정자에게 자급자족해야 한다.
  1. "Phase 0~6 을 그대로 수행" 만 있으면 판정자는 확인할 수 없다. `[완료 조건]` 을 명시한다.
  2. 산출물을 출력으로 확인하게 쓴다: 경로 존재 `ls`, 행 수, PR URL, `gh pr view --json state`, 보고서 섹션 `grep`.
  3. 명세의 체크리스트와 결정 기록을 마지막 턴에 출력하게 한다: `grep -c '^- \[ \]' {명세}` → `0`, `sed -n '/^## 결정 기록/,/^## /p' {명세}`.
  4. 금지 사항에 확인 명령을 붙인다: `git status --porcelain`, `git -C {다른 체크아웃} status`.

런처 골격:

```text
[목표] {끝난 상태 한 문장}. 배경·인벤토리·절차의 정본은 `{명세 경로}` — 시작하자마자 읽고, 항목을 끝낼 때마다 체크한다. 판정 기준은 아래 C 항목뿐이다.
[완료 조건] 아래 C1–C{n}이 모두 참일 때만 완료로 본다.
C1. 명세 인벤토리 전부 완료 — 확인: `grep -c '^- \[ \]' {명세 경로}` → `0`, `grep -c '^- \[x\]' {명세 경로}` → `{항목 수}` 이상.
C2. {전체 게이트: 테스트·빌드·타입} — 확인: `{명령} 2>&1 | tail -n 15; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`.
C3. {핵심 요구사항 중 판정자가 직접 봐야 하는 것} — 확인: `{명령}` → {기대값}.
[증거 규칙] 완료를 주장하는 턴에서 C1–C{n} 명령을 다시 실행하고 `sed -n '/^## 결정 기록/,/^## /p' {명세 경로}` 를 출력한다. 최종 메시지에 `C1 ✅ <근거 원문 한 줄>` 체크리스트를 쓴다.
[제약] (위반하면 미완료) {금지 사항}. 확인: `git status --porcelain -- {보호 경로}` 출력이 비어 있음.
[막힘·중단] 사용자에게 묻지 않는다. 명세에 없는 결정은 명세의 기본값을 적용하고 `## 결정 기록` 에 남긴다. 같은 원인으로 3번 연속 실패하면 `GOAL-STATUS: BLOCKED — <원인>`. 턴마다 `GOAL-TURN k/{N}`, {N}턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>`. 둘 다 종료로 인정한다.
[참고] (판정 대상 아님) 명세: `{명세 경로}`
```

명세 골격:

```markdown
# {목표 한 줄}

판정 기준은 goal 런처의 C 항목이다. 이 파일은 배경·인벤토리·절차다. 항목을 끝내면 `- [x]` 로 바꾼다.

## 배경
## 인벤토리
- [ ] R1. {항목} — {항목별 완료 기준}
- [ ] R2. …
## 절차
## 결정 기록
| 항목 | 기본값 | 근거 |
| --- | --- | --- |
## 진행 표
```

- Codex 런처는 "정본은 `{명세}` — 먼저 읽고 체크리스트를 갱신한다" 로 충분히 가리킬 수 있다. 다만 TUI 상태 표시와 continuation 은 objective 만 보므로 핵심 완료 조건은 런처에도 둔다.
- Codex TUI 의 자동 파일화(4,000자 초과 입력을 파일로 뺌)에 기대지 않는다. objective 가 포인터 한 줄이 된다.

## 6. 작업 유형별 게이밍 차단 제약

goal 을 만들 때 유형에 맞는 항목을 `[제약]` 과 C 항목에 넣는다. 명령은 프로젝트에 맞게 바꾼다.

**공통**

- 보호 경로 수정 금지 — 확인: `git diff --stat -- {보호 경로}` 빈 출력. 새 파일(untracked)은 `git diff` 에 안 잡히므로 `git status --porcelain -- {경로}` 를 쓴다.
- 커밋을 허용하면 `git status` 와 `git diff` 는 커밋된 변경을 보지 못한다. 커밋·push 금지로 두거나, 시작 커밋을 출력해 두고 `git diff --stat {시작 커밋} -- {경로}` 로 비교한다.
- 억제 주석 추가 금지 — 확인: `git diff -U0 | grep -cE '^\+.*(eslint-disable|@ts-ignore|@ts-expect-error|type: ignore|noqa|istanbul ignore|v8 ignore|pragma: no cover)'` → `0`.
- push, 배포, 삭제, 운영 DB 는 goal 문구만 믿지 않는다. settings deny 와 sandbox 로 막는다.

| 유형 | 넣을 제약과 C 항목 | 턴 상한 기본 | Codex budget 제안 |
| --- | --- | --- | --- |
| bugfix | 재현 테스트가 수정 전에 실패한 출력 인용(`1 failed`) → 수정 후 `1 passed`. 기존 테스트·스냅샷·테스트 설정 수정 금지(새 테스트 추가만). `skip`/`only`/retries 증가/timeout 연장/assert 완화 금지. 전체 스위트 `EXIT=0`, 테스트 수 ≥ 기준선. 최종 메시지에 원인 한 줄 + `git diff --stat` | 25 | 100k–500k |
| feature | 수용 기준마다 테스트 이름이나 필터 명령(`--tests '*Header*'`) → `passed`, 대상 테스트 최소 개수. 기존 공개 계약(요청·응답 형식, 공개 시그니처) 불변. 기존 테스트 수정·삭제 금지. 새 의존성 금지 — 확인: `git diff --stat -- package.json {lockfile}` 빈 출력. `[범위 밖]` 에 UI·다른 포맷. 명세에 없는 결정은 기본값 + 결정 기록 | 30 | 500k–2M |
| refactor | 테스트 코드 무변경 — `git status --porcelain -- {테스트 경로}` 빈 출력. 공개 API 불변 — 시작 시 시그니처 목록 저장, 종료 시 `diff` 빈 출력. 크기 지표 `wc -l` ≤ N. 동작 변경·기능 추가·성능 최적화 금지. 테스트 수 ≥ 기준선 | 40 | 500k–2M |
| research | 판정자는 파일을 못 읽는다 → 필수 섹션 `grep -cE '^## (…)$'` → N, 표 검사 스크립트 `rows=… missing=0`, 요약 `sed -n`. 확인 못 한 수치는 `미확인` 으로 적고 `## 미확인 항목` 에 모은다(추정 금지). 출처는 공식 도메인 검사 `non_official=0`. 접근 불가 자원은 `미확인` 으로 두고 계속. 코드 수정 금지 — `git status --porcelain -- src` 빈 출력 | 20 | 100k–500k |
| coverage | 범위를 고정한 수치 출력(`--coverage.include=… --coverage.reporter=text-summary … \| tail -n 8`) `Lines ≥ N%`. 커버리지 설정(include/exclude/thresholds)·소스 수정 금지 — 바뀐 파일은 테스트뿐 `git status --porcelain \| grep -vE '\.test\.ts$'` 빈 출력. ignore 주석 금지. 새 테스트마다 `expect` ≥ 1, 스냅샷 전용 테스트 0 | 30 | 500k–2M |
| migration | 잔존 패턴 0 — `grep -rnE '{구 API 패턴}' {경로} \| wc -l` → `0`. 호환층·shim·feature flag·래퍼로 "동작" 만 맞추기 금지 (호환층 import 도 잔존 패턴에 넣는다, 예: `pydantic.v1`). 억제 주석 추가 0. passed 수 ≥ 기준선, 테스트 기대값 수정 금지. 구 의존성 제거 확인(`grep -c '"moment"' package.json` → `0`) | 40 | 2M–10M |
| docs | 필수 섹션 `grep -n '^## '` 출력. 깨진 링크 0 (프로젝트 링크 검사기, 예: `lychee --offline docs/`). 문서 밖 파일 수정 금지 — `git status --porcelain \| grep -vE '\.md$'` 빈 출력. 코드 예시는 실제로 돈다(추출해 실행하거나 doctest). 비밀값 없음 — `grep -rniE '(api[_-]?key\|token\|password)\s*[:=]' docs/ \| wc -l` → `0` | 20 | 100k–500k |
| other | 공통 제약. 산출물은 존재가 아니라 내용(행 수, 섹션, 값)으로 확인한다 | 25 | 500k–2M |

## 7. 길이 초과 시 압축 사다리

`check_goal.py` 가 길이 오류를 내면 위에서부터 한 칸씩 적용하고 다시 검사한다. 검사는 모두 합쳐 5회까지다. 첫 초안이 제한의 1.5배(6,000자) 이상이면 1–5 를 건너뛰고 바로 6 으로 간다.

1. **`[참고]` 삭제·축소.** 판정 대상이 아니므로 먼저 뺀다. 명세 경로 한 줄만 남긴다.
2. **`[범위 밖]` 축소.** 명사 나열 한 줄(80자 안팎)로 줄이거나 지운다. 범위는 `[목표]` 가 이미 정한다.
3. **문장 압축.**
   - "…를 확인한다", "…인 상태여야 한다" 같은 서술을 `— 확인:` 형식 하나로 줄인다.
   - C 항목마다 반복되는 `2>&1 | tail -n 20; echo "EXIT=${PIPESTATUS[0]}"` 를 `[증거 규칙]` 의 공통 규칙 한 줄로 옮긴다. 예: "모든 확인 명령은 `2>&1 | tail -n 15` 로 줄이고 `EXIT=${PIPESTATUS[0]}` 를 찍는다". C 항목에는 명령 본체만 둔다.
   - 요약 줄만 필요하면 `tail -n 20` 을 `tail -n 5` 로 줄인다.
   - 같은 경로를 여러 번 쓰면 `[목표]` 에서 한 번 적고 `<파일>` 로 부른다 (examples.md 4번).
   - 괄호 설명과 예시를 지운다.
4. **겹치는 C 항목 병합.** 같은 명령이나 같은 스크립트 출력으로 확인되는 항목을 합친다(예: `rows=… missing=0 non_official=0`). **3개 미만으로 줄이지 않고, 확인 명령과 게이밍 차단 확인을 잃지 않는다.**
5. **배경·절차를 명세 파일로.** 판정 기준이 아닌 문장(배경, 순서, 방법)을 명세 파일로 옮기고 `[참고]` 에 경로만 둔다. Claude 대화형이면 배경을 `/goal` 앞의 일반 메시지로 먼저 주는 2단계 시작도 된다.
6. **런처 + 명세 (5절).** 그래도 넘치면 인벤토리와 항목별 요구사항까지 명세로 옮긴다. C 항목은 명세 체크리스트를 출력으로 확인하는 집계 조건으로 바꾼다. 명세를 쓴 뒤 런처를 다시 검사한다.

어느 단계에서도 지우지 않는 것: `[목표]`, C 항목의 확인 명령과 기대값, 게이밍 차단 제약과 그 확인 명령, `GOAL-STATUS` 종료 절(Claude).

## 8. check_goal.py 규칙

```bash
python scripts/check_goal.py <파일|-> [--target claude|codex] [--limit 4000] [--shell bash|powershell] [--json]
```

- 길이는 맨 앞 `/goal` 토큰을 떼고 앞뒤 공백을 자른 뒤 센다. claude 는 `len(text.encode('utf-16-le')) // 2`(JS length), codex 는 `len(text)`(code point) 다. 줄바꿈은 LF 로 맞추고, 파일 전체를 감싼 ``` 울타리와 UTF-8 BOM 은 뗀다.
- 종료 코드: 0 통과(경고만 있어도 0), 1 오류, 2 사용법·입력 오류(파일 없음, UTF-8 아님, 잘못된 옵션).
- 출력 첫 줄: `길이: 3,120 / 4,000자 (claude, UTF-16 기준) · 검사 통과`. 이어서 섹션별 길이, 오류, 경고. `--json` 은 `ok, target, unit, length, limit, soft_limit, over, sections, c_items, errors, warnings, notes`.
- 섹션 머리는 공백과 구분 기호를 무시하고 비교한다. `[막힘·중단]` `[막힘 / 중단]` `[막힘ㆍ중단]` `[막힘]` 은 같은 섹션이다. 같은 이름이 줄 가운데 다시 나오면(본문 속 언급) 섹션을 나누지 않는다.

**오류 (반드시 고친다)**

| 코드 | 조건 |
| --- | --- |
| `length` | 길이 > 제한 (기본 4,000) |
| `empty` | `/goal` 을 떼고 나면 비어 있다 |
| `section-missing` | `[목표]` `[완료 조건]` `[제약]` `[막힘·중단]` 이 없다. claude 는 `[증거 규칙]` 도 필수 |
| `no-c-items` | C1, C2 … 항목이 하나도 없다 |
| `c-no-check` | `확인` 이 없는 C 항목 |
| `template-token` | 채우지 않은 `{…}` 자리표시(한글·`…`·`n`·`N` 을 담은 중괄호), `…(3–7개)` 같은 템플릿 줄. `${VAR}`, `{}`, `{3}`, JSON 은 제외 |
| `no-goal-status` | claude 인데 `GOAL-STATUS` 종료 절이 없다 |

**경고 (고치거나, 남기면 이유를 가정에 적는다)**

| 코드 | 조건 |
| --- | --- |
| `length-soft` | 길이 > 3,500 (제한이 작으면 제한의 87.5%) |
| `front-500` | `[목표]` 나 `[완료 조건]` 머리가 앞 500자 밖에 있다 |
| `c-count` / `c-numbering` | C 항목이 3–7개가 아니다 / 번호가 C1 부터 이어지지 않는다 |
| `c-no-command` | 백틱으로 감싼 확인 명령이 없는 C 항목 (경로·식별자·기대값만 있는 백틱은 명령으로 치지 않는다) |
| `c-no-expected` | 기대값 표시(→, `EXIT=`, ≥, `= 0`, 0건, passed, 비어 있음, 로 시작 등)가 없는 C 항목 |
| `judge-file-only` | claude 에서 C 항목이 파일만 가리키고 출력 명령이 없다 (판정자는 파일을 못 읽는다) |
| `subjective` | `[목표]`·`[완료 조건]` 에 판정할 수 없는 표현: 깔끔, 잘, 적절, 충분, 최적, 완벽, 개선, 가능한 한, 최대한, 제대로, production-ready 등. `[제약]`·`[범위 밖]` 의 "최적화 금지" 는 괜찮다 |
| `codex-turn-cap` | codex 에 "N턴 후 중단", `GOAL-TURN`, `STOPPED` 같은 턴 상한 절. "3턴 연속" 은 괜찮다 |
| `codex-no-report` | codex 에 `[보고]` 도 `[증거 규칙]` 도 없다 |
| `no-turn-cap` | claude 에 `GOAL-STATUS` 는 있는데 `GOAL-TURN`/`STOPPED` 턴 상한이 없다 |
| `evidence-rerun` | claude `[증거 규칙]` 에 "다시 실행" 이 없다 |
| `shell-idiom` | `--shell powershell` 인데 `PIPESTATUS` 나 `EXIT=$?`($? 는 True/False) / `--shell bash` 인데 `$LASTEXITCODE`, 또는 파이프 뒤 `$?` (tail 의 코드가 찍힌다) |
| `constraint-no-check` | `[제약]` 에 금지 조항이 있는데 확인 명령이 `[제약]` 에도 없고 goal 어디에도 `git diff`/`git status` 가 없다 |

참고 줄: `--limit` 이 4,000 보다 크면 "Claude Code·Codex 의 실제 제한은 4,000자" 를 알린다.

## 9. 안티패턴 체크리스트

**판정 가능성**

- [ ] 활동 동사만 있고 끝난 상태가 없다 ("고쳐", "추가해", "개선해", "조사해")
- [ ] 주관 형용사가 있다 (깔끔, 잘, 충분히, 적절히, 최적, 완벽, production-ready, 읽기 좋게)
- [ ] 완료 조건에 확인 명령이나 기대값이 빠진 항목이 있다
- [ ] (Claude) 판정 기준이 파일 안에만 있다 ("스펙대로", "PLAN.md 전부")
- [ ] 판정자가 볼 수 없는 상태를 요구한다 (커버리지 리포트, 브라우저 화면, 외부 대시보드를 출력하지 않음)
- [ ] 사람의 행동이나 미래 사건에 기댄다 (승인, 머지, 배포 뒤 모니터링, "사용자가 만족")

**사소하게 참 / 게이밍**

- [ ] "테스트 통과" 에 범위, 최소 개수, 기준선이 없다
- [ ] 테스트, 스냅샷, golden, 설정(threshold, exclude, retries, timeout) 수정 금지가 없다
- [ ] 금지 조항에 확인 명령이 없다 (`git diff --stat -- …`, `git status --porcelain`)
- [ ] 커밋을 허용하면서 `git status` 로만 보호 경로를 확인한다
- [ ] 억제 주석(`type: ignore`, `eslint-disable`, `istanbul ignore`, `@ts-ignore`)을 허용한다
- [ ] "보고서/파일이 존재" 만 요구한다 (섹션, 행 수, 출처 검사가 없다)
- [ ] 호환층, shim, feature flag 로 "동작" 만 맞추는 우회를 막지 않았다 (마이그레이션)

**영원히 거짓 / 무한 루프**

- [ ] 무한 범위("모든 버그", "완전히")나 서로 모순되는 제약이 있다
- [ ] 샌드박스나 네트워크에서 접근할 수 없는 자원이 필수다 (대체 경로가 없다)
- [ ] (Claude) 종료 절(BLOCKED/STOPPED)과 턴 상한이 없다 / (Codex) token budget 이 없다
- [ ] 회색지대에서 사용자에게 묻도록 되어 있다 (기본값과 기록 위치가 없다)

**증거 전달**

- [ ] 마지막 턴 재검증 요구가 없다 (초반 증거는 transcript 절단이나 compaction 으로 사라진다)
- [ ] 출력이 길다. tail 이나 요약 없이 수천 줄이면 앞 2KB 만 남는다
- [ ] exit code 를 명시적으로 찍지 않는다 (Claude Bash 도구는 실패할 때만 보여 준다)
- [ ] 최종 체크리스트(`Cn ✅ <원문 한 줄>`) 요구가 없다

**형식·운영**

- [ ] 4,000자 초과 / 핵심이 뒤쪽에 있다 (앞 500자에 목표와 완료 조건이 없다)
- [ ] 한 goal 에 결과물이 여러 개다
- [ ] 배경이나 절차 설명이 판정 기준과 섞여 있다 (`[참고] (판정 대상 아님)` 라벨이 없다)
- [ ] 확인 명령이 권한 allowlist 에 없다 / 긴 명령을 백그라운드로 돌려 평가가 계속 미뤄진다
- [ ] 위험 작업(push, 배포, 삭제) 금지를 goal 문구에만 기댄다 (settings deny, sandbox 없음)
- [ ] (Codex) 요청하지 않은 token budget 을 모델이 걸게 두었다 / 턴 상한 절을 넣어 continuation 규칙과 충돌한다

## 10. 실행 전 체크와 권한

스킬은 goal 과 함께 아래를 사용자에게 보여 준다 (goal 밖에).

- [ ] 확인 명령을 모두 권한 프롬프트 없이 실행할 수 있는가 (auto mode 또는 allowlist)
- [ ] 시작 전에 확인 명령을 한 번 돌려 **기준선** 과 **명령 자체가 동작하는지** 확인했는가
- [ ] 보호 경로가 git 으로 추적되는가 (untracked 파일은 `git diff` 에 안 잡힌다. `git status --porcelain` 을 쓴다)
- [ ] Claude 대화형: 턴 절이 있는가 / headless: `--max-turns`, `--max-budget-usd`
- [ ] Codex: token budget, sandbox 네트워크 가정, plan mode 를 먼저 거칠지

권한 허용 목록 (Claude Code `.claude/settings.json` 의 `permissions.allow`) 예:

```json
{ "permissions": { "allow": ["Bash(pnpm test:*)", "Bash(pnpm exec playwright test:*)", "Bash(pnpm typecheck:*)", "Bash(git diff:*)", "Bash(git status:*)", "Bash(grep:*)", "Bash(wc:*)", "Bash(tail:*)"] } }
```

- `&&`, `|`, `;` 로 이은 명령은 각 부분이 모두 허용돼야 한다. `tail`, `grep`, `wc`, `echo` 도 넣는다.
- 허용 목록을 만들기 번거로우면 auto mode 를 쓴다.
- push, 배포, 삭제는 `deny` 에 넣는다.
- Codex 는 approval·sandbox 설정이 확인 명령을 막지 않는지 본다.

## 11. goal 을 쓰지 말아야 할 때

아래 작업은 일반 프롬프트, `/plan`, 대화형 진행이 낫다. 스킬은 goal 을 만들기 전에 이렇게 권한다.

- 한 번에 끝나는 작업
- 탐색이나 디자인 판단이 중심인 작업
- 중간에 사람의 결정이 꼭 필요한 작업
- 자격 증명, 운영 DB, 인프라를 건드리는 작업
- 결과가 여러 개 섞인 작업: 순차 goal 로 나눈다

## 12. 출처

- Claude Code — Keep Claude working toward a goal: https://code.claude.com/docs/en/goal
- Claude Code — Hooks guide (prompt hook, Stop hook block cap): https://code.claude.com/docs/en/hooks-guide
- Claude Code CHANGELOG (`/goal` 2.1.139 이후): https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
- Claude prompting best practices (테스트 수정 금지, hard-coding 회피): https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices
- Anthropic Engineering — Effective harnesses for long-running agents: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- OpenAI — Long-running work / Goal mode: https://learn.chatgpt.com/codex/long-running-work
- OpenAI Cookbook — ExecPlans (관찰 가능한 수용 기준): https://developers.openai.com/cookbook/articles/codex_exec_plans
- Codex `MAX_THREAD_GOAL_OBJECTIVE_CHARS = 4_000`: https://github.com/openai/codex/blob/rust-v0.145.0/codex-rs/protocol/src/protocol.rs
- Codex TUI 긴 objective 파일화: https://github.com/openai/codex/blob/rust-v0.145.0/codex-rs/tui/src/goal_files.rs
- Codex goal 확장 (continuation.md, budget_limit.md): https://github.com/openai/codex/tree/rust-v0.145.0/codex-rs/ext/goal
- Codex 요청받지 않은 token budget 사고: https://github.com/openai/codex/issues/24629
- OpenChamber `SESSION_GOAL_OBJECTIVE_CHAR_LIMIT = 5000`: https://github.com/openchamber/openchamber/blob/main/packages/ui/src/lib/sessionGoalMetadata.ts
- Claude Code 바이너리 값 (판정자 설정, 4000, 500, 2KB 미리보기, 차단 상한 8): 연구 당시 2.1.285 설치본에서 추출. 버전이 오르면 다시 확인한다.
