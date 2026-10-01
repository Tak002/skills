# make-goal 예시 — 나쁜 goal → 좋은 goal

연구 보고서(2026-09-30, `/goal` 프롬프트 작성 연구) 7절의 예시 6종을 옮겼다. 모두 Claude Code 용이고, 마지막 마이그레이션에는 Codex 변형을 붙였다. 좋은 goal 은 스킬이 사용자에게 내놓는 모양 그대로(`/goal ` 로 시작) 적었고, 괄호 안 길이는 `scripts/check_goal.py` 로 잰 값이다.

보고서 원문에서 바꾼 점 (모두 `check_goal.py` 경고를 없애거나 게이밍 구멍을 막는 방향):

- C 항목마다 백틱 확인 명령과 기대값을 붙였다. 원문은 일부 항목이 "테스트 통과", "스크립트 출력" 처럼 명령이나 기대값 없이 끝났다 (1번 C1, 2번 C1–C3, 3번 C5, 4번, Codex 변형). 4번은 같은 스크립트로 확인하던 두 항목을 하나로 합쳤다.
- 3번(리팩터)은 "추출 단위로 커밋" 을 "커밋·push 금지" 로 바꿨다. 커밋하면 `git status --porcelain` 이 비어 버려 "테스트 무변경" 검사가 사소하게 참이 된다.
- 4번(리서치)은 목표에 있는 "한국어 품질" 을 완료 조건에도 넣었고, 보고서 경로를 상대 경로로 바꿨다.
- 1·2번은 금지 조항(`server/` 수정 금지, 의존성·기존 테스트 변경 금지)에 확인 명령을 붙였다.
- Codex 변형의 C 항목에도 `확인:` 을 붙였고, 섹션 이름을 Claude 판과 같게(`[막힘·중단]`) 맞췄다.

`tests/test_check_goal.py` 가 `<!-- goal: 대상 -->` 표시가 붙은 코드 블록을 모두 검사한다 (오류·경고 0, 괄호 안 길이 일치). 예시를 고치면 테스트를 다시 돌린다.

## 1. 버그 수정 (bugfix)

나쁜 예: `/goal 로그인 버그 고쳐줘`

- 활동만 있고 끝난 상태가 없다. "고쳤습니다" 라는 주장만으로 판정자가 넘어가거나, 증거가 없어 `insufficient evidence` 루프에 빠진다.
- 회귀 검사가 없다.
- 재현 테스트 없이 증상만 가리는 수정이나 timeout 연장을 막지 못한다.

좋은 예 (Claude Code, 1,220자):

<!-- goal: claude -->
```text
/goal [목표] 세션 만료 직후 새로고침하면 /login 대신 빈 화면이 뜨는 버그(이슈 #412)를 원인 수준에서 고친다.
[완료 조건] 아래 C1–C4가 모두 참일 때만 완료로 본다.
C1. 재현 테스트 `client/e2e/session-expiry.spec.ts`가 추가됐고 수정 전 코드에서 실패했다 — 확인: 수정 전에 실행한 `pnpm exec playwright test e2e/session-expiry.spec.ts 2>&1 | tail -n 15` 의 실패 출력(에러 1~3줄)을 최종 메시지에 인용 → `1 failed`.
C2. 수정 후 같은 테스트 통과 — 확인: `pnpm exec playwright test e2e/session-expiry.spec.ts 2>&1 | tail -n 15` 에 `1 passed`, failed 없음.
C3. 기존 스위트 회귀 없음 — 확인: `pnpm test 2>&1 | tail -n 20; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`.
C4. 타입체크 통과 — 확인: `pnpm typecheck; echo "EXIT=$?"` → `EXIT=0`.
[증거 규칙] 완료를 주장하는 턴에서 C2–C4 명령을 다시 실행해 출력이 tool 결과에 그대로 남게 한다. 최종 메시지에 `C1 ✅ <근거 원문 한 줄>` 형식의 체크리스트, 원인 한 줄, `git diff --stat` 을 쓴다. 이전 턴의 기억이나 요약은 증거가 아니다.
[제약] (위반하면 미완료) 기존 테스트·스냅샷·`playwright.config.ts` 수정 금지(새 spec 추가만 허용). `test.skip`/`.only`/retries 증가/timeout 연장으로 통과시키기 금지. `server/` 수정 금지. 확인: `git diff --stat -- server client/playwright.config.ts client/e2e ':!client/e2e/session-expiry.spec.ts'` 출력이 비어 있음.
[막힘·중단] 사용자에게 묻지 않는다. 같은 원인(예: 로컬 서버 기동 실패)으로 3번 연속 실패하면 시도한 명령과 에러를 적고 `GOAL-STATUS: BLOCKED — <원인>`을 출력한다. 턴마다 마지막 줄에 `GOAL-TURN k/25`를 쓰고, 25턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>`을 출력한다. 둘 중 하나가 최종 메시지에 있으면 종료로 인정한다.
```

## 2. 기능 추가 (feature)

나쁜 예: `/goal 주문 CSV 내보내기 기능 추가하고 테스트도 작성해`

- "추가했다" 와 "작성했다" 는 아무 엔드포인트, 아무 테스트로도 참이 된다. 테스트가 통과해야 한다는 조건조차 없다.
- 범위(UI? XLSX?)가 열려 있다.
- 명세의 수용 기준을 판정자가 볼 수 없다.

좋은 예 (Claude Code, 1,451자):

<!-- goal: claude -->
```text
/goal [목표] 주문 목록의 현재 필터 결과를 CSV로 내려받는 `GET /api/orders/export.csv`를 추가한다. (참고 명세: docs/specs/order-export.md — 판정 기준은 아래 C1–C5뿐)
[완료 조건] C1–C5가 모두 참일 때만 완료.
C1. 헤더 행이 정확히 `order_id,ordered_at,customer_name,status,total_krw` 이고 UTF-8 BOM으로 시작한다 — 확인: `./gradlew test --tests '*OrderExportControllerTest*Header*' 2>&1 | tail -n 5` → `BUILD SUCCESSFUL`.
C2. 목록 API와 같은 필터(status, from, to)를 받고 결과 행 집합이 목록 API와 같다 — 확인: `./gradlew test --tests '*OrderExport*FilterParity*' 2>&1 | tail -n 5` → `BUILD SUCCESSFUL`.
C3. 10,000행을 스트리밍으로 내보낸다 — 확인: `grep -rn "StreamingResponseBody" src/main | head -n 3` 인용 + `./gradlew test --tests '*OrderExport*TenThousandRows*' 2>&1 | tail -n 5` → `BUILD SUCCESSFUL`.
C4. 대상 테스트 — 확인: `./gradlew test --tests '*OrderExport*' 2>&1 | tail -n 25` 에 PASSED 5개 이상, FAILED 0.
C5. 전체 테스트 — 확인: `./gradlew test 2>&1 | tail -n 5; echo "EXIT=${PIPESTATUS[0]}"` → `BUILD SUCCESSFUL`, `EXIT=0`.
[증거 규칙] 완료를 주장하는 턴에서 C1–C5를 다시 실행한다. 최종 메시지에 C1–C5 체크리스트(항목마다 출력 원문 한 줄)와 `curl -s 'localhost:8080/api/orders/export.csv?status=PAID' | head -n 3` 결과를 붙인다.
[제약] 기존 엔드포인트의 요청·응답 형식 변경 금지. 새 의존성 추가 금지. 기존 테스트 수정·삭제 금지. 인증 없는 접근 허용 금지. 확인: `git diff --stat -- build.gradle src/test` 출력이 비어 있음(새 테스트 파일 추가는 허용).
[범위 밖] 프런트엔드 버튼, XLSX, 비동기 대용량 내보내기.
[막힘·중단] 명세에 없는 결정(날짜 포맷 등)은 묻지 말고 ISO-8601로 정한 뒤 최종 메시지의 "결정 기록"에 남긴다. 같은 원인으로 3번 연속 실패하면 `GOAL-STATUS: BLOCKED — <원인>`, 턴마다 `GOAL-TURN k/30`을 쓰고 30턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>`(둘 다 종료로 인정).
```

## 3. 리팩터 (refactor)

나쁜 예: `/goal PatientService를 깔끔하게 리팩토링해서 유지보수하기 좋게 만들어`

- "깔끔", "유지보수하기 좋게" 는 판정할 수 없다. 판정자가 끝없이 not met 을 내거나, 반대로 아무 변경에나 수긍한다.
- 동작이 바뀌어도, 테스트를 고쳐도 막을 장치가 없다.

좋은 예 (Claude Code, 1,090자):

<!-- goal: claude -->
```text
/goal [목표] `PatientService.java`(현재 1,240줄)를 동작 변경 없이 책임별 클래스로 분리한다.
[완료 조건] C1–C5가 모두 참일 때만 완료.
C1. `PatientService.java` ≤ 300줄, 새 클래스 각각 ≤ 400줄 — 확인: `git status --porcelain -- src/main` 에 나온 .java 파일들의 `wc -l` 출력.
C2. `PatientService`의 public 시그니처 불변 — 확인: 시작 시 `grep -E '^\s+public ' PatientService.java | sort > build/tmp/api-before.txt`, 종료 시 같은 방법으로 만든 api-after.txt와 `diff` 결과가 비어 있음.
C3. 테스트 코드 무변경 — 확인: `git status --porcelain -- src/test` 출력이 비어 있음.
C4. 전체 테스트 통과, 테스트 수 유지 — 확인: `./gradlew test 2>&1 | tail -n 8; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`, 테스트 수 ≥ 시작 시 기준선.
C5. 새 파일은 모두 `.../patient/` 패키지 아래 — 확인: `git status --porcelain | grep '^??' | grep -vc '/patient/'` → `0`.
[증거 규칙] 시작 시 기준선(테스트 수, api-before.txt)을 만들고 출력한다. 완료를 주장하는 턴에서 C1–C5 명령을 다시 실행하고 최종 메시지에 기준선 대비 수치와 체크리스트를 쓴다.
[제약] 동작 변경·기능 추가·성능 최적화 금지. `@Transactional` 경계 유지. DB 스키마·컨트롤러 수정 금지. 커밋·push 금지(변경은 작업 트리에 남긴다).
[막힘·중단] 분리 경계가 애매하면 묻지 말고 도메인 명사(등록/입원/청구) 기준으로 나누고 근거를 남긴다. 3번 연속 테스트 실패로 되돌리게 되면 `GOAL-STATUS: BLOCKED — <원인>`, 턴마다 `GOAL-TURN k/40`, 40턴 초과 시 `GOAL-STATUS: STOPPED — <남은 일>`(둘 다 종료로 인정).
```

## 4. 리서치·보고서 (research)

나쁜 예: `/goal LLM 모델들 비교해서 보고서 써줘`

- 판정자는 보고서 파일을 읽을 수 없다. "보고서 작성" 은 빈 파일로도 참이다.
- 수치 출처 요구가 없어 추정치나 환각이 섞인다.
- 몇 개 모델을, 어떤 축으로 비교할지 없어 끝이 없다.

좋은 예 (Claude Code, 991자):

<!-- goal: claude -->
```text
/goal [목표] 차트 요약 기능 후보 LLM 6종 이상의 비용·한국어 품질 비교 보고서 `report/vetsync/2026-10-01-llm-choice.md`(아래 `<파일>`)를 완성한다.
[완료 조건] C1–C4가 모두 참일 때만 완료.
C1. 섹션 `## 요약`, `## 비교표`, `## 가정`, `## 미확인 항목`, `## 출처`가 모두 있다 — 확인: `grep -cE '^## (요약|비교표|가정|미확인 항목|출처)$' <파일>` → `5`.
C2. 비교표에 모델 6행 이상, 행마다 입력/출력 1M 토큰 단가(USD)·한국어 벤치마크 점수(없으면 `미확인`)·출처 URL·확인 날짜가 있고 단가 출처는 제공사 공식 도메인이다 — 확인: `python tools/check_llm_table.py <파일>` → `rows=<n> missing=0 non_official=0` (n ≥ 6).
C3. 병원 1곳 월 원가를 질의량 3가지 가정(1천/1만/5만 건)으로 계산했다 — 확인: `python tools/cost_calc.py` 출력 → 가정 3행 모두 금액이 있음.
C4. `## 요약`은 결론 1문장 + 권고 모델 1개 + 근거 3개 이내 — 확인: `sed -n '/^## 요약/,/^## 비교표/p' <파일>` 출력.
[증거 규칙] 판정자는 파일을 읽을 수 없다. 완료를 주장하는 턴에서 C1–C4 확인 명령을 다시 실행해 출력이 transcript에 남게 한다.
[제약] 확인 못 한 수치는 추정하지 말고 `미확인`으로 적고 `## 미확인 항목`에 이유와 함께 모은다. 블로그·집계 사이트는 보조 출처로만. 코드는 수정하지 않는다 — 확인: `git status --porcelain -- src` 출력이 비어 있음.
[막힘·중단] 가격 페이지 접근이 막힌 모델은 `미확인`으로 두고 계속한다. 턴마다 `GOAL-TURN k/20`, 20턴을 넘기면 현재 보고서를 저장하고 `GOAL-STATUS: STOPPED — <남은 일>`(종료로 인정).
```

## 5. 테스트 커버리지 (coverage)

나쁜 예: `/goal 테스트 커버리지 80% 이상으로 올려`

- 범위(전체? 모듈?)와 지표(line? branch?)가 없다.
- 커버리지 수치가 출력되지 않으면 판정할 수 없다.
- exclude 설정 확장, `istanbul ignore` 주석, assert 없는 테스트, 스냅샷 남발로 쉽게 속일 수 있다.

좋은 예 (Claude Code, 966자):

<!-- goal: claude -->
```text
/goal [목표] `src/billing/**` 의 line coverage를 85% 이상으로 올린다(현재 약 61%).
[완료 조건] C1–C4가 모두 참일 때만 완료.
C1. 커버리지 — 확인: `pnpm vitest run src/billing --coverage --coverage.include='src/billing/**' --coverage.reporter=text-summary 2>&1 | tail -n 8` 의 `Lines` ≥ 85%.
C2. 전체 스위트 통과 — 확인: `pnpm test 2>&1 | tail -n 10; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`.
C3. 바뀐 파일은 테스트 파일뿐 — 확인: `git status --porcelain | grep -v -E '\.test\.ts$'` 출력이 비어 있음.
C4. 새 테스트마다 동작 검증 `expect`가 있고 스냅샷 전용 테스트가 없다 — 확인: 새 테스트 파일별 `grep -c "expect("` ≥ 1, `grep -c "toMatchSnapshot"` = 0.
[증거 규칙] 시작 시 C1 명령으로 기준선을 출력한다. 완료를 주장하는 턴에서 C1–C4를 다시 실행하고 최종 메시지에 기준선 → 최종 수치와 체크리스트를 쓴다.
[제약] coverage 설정(`vitest.config.ts` include/exclude/thresholds)·`package.json`·소스 코드 수정 금지. `v8 ignore`/`istanbul ignore` 주석 금지. 구현 세부를 복제하지 말고 공개 함수의 입력·출력을 검증한다.
[막힘·중단] 소스 수정 없이는 85%가 불가능하다고 판단되면 근거(미도달 파일·라인)를 적고 `GOAL-STATUS: BLOCKED — <원인>`. 턴마다 `GOAL-TURN k/30`, 30턴 초과 시 `GOAL-STATUS: STOPPED — <현재 수치>`(둘 다 종료로 인정).
```

## 6. 마이그레이션 (migration)

나쁜 예: `/goal Pydantic v2로 마이그레이션 완료`

- "완료" 를 판정할 수단이 없다.
- `from pydantic.v1 import …` 호환층으로 바꾸기만 해도 "동작" 해서 사소하게 참이 된다.
- 잔존 패턴 검사가 없다.
- `type: ignore` 로 타입 오류를 덮을 수 있다.

좋은 예 (Claude Code, 921자):

<!-- goal: claude -->
```text
/goal [목표] `app/` 전체를 Pydantic v2 API로 옮기고 v1 호환층 사용을 없앤다.
[완료 조건] C1–C5가 모두 참일 때만 완료.
C1. 설치 버전 — 확인: `python -c "import pydantic; print(pydantic.VERSION)"` → `2.`로 시작.
C2. v1 API 잔존 0건 — 확인: `grep -rnE "pydantic\.v1|@validator\(|@root_validator\(|\.parse_obj\(|class Config:" app/ | wc -l` → `0`.
C3. 테스트 — 확인: `pytest -q 2>&1 | tail -n 5; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`, passed 수 ≥ 시작 시 기준선.
C4. 타입 — 확인: `mypy app/ 2>&1 | tail -n 3` → `Success`.
C5. 억제 주석 추가 없음 — 확인: `git diff -U0 | grep -cE "^\+.*(type: ignore|noqa)"` → `0`.
[증거 규칙] 시작 시 C2·C3 기준선을 출력한다. 완료를 주장하는 턴에서 C1–C5를 다시 실행하고 최종 메시지에 체크리스트와 `git diff --stat | tail -n 1`을 쓴다.
[제약] 공개 API 응답 JSON 형식 변경 금지(필드 이름·null 처리 유지). 테스트 기대값 수정 금지. 의존성은 pydantic·pydantic-settings만 변경.
[막힘·중단] 서드파티 라이브러리가 v1을 요구하는 모듈은 목록으로 남기고 나머지를 계속한다. 같은 원인 3회 연속 실패 시 `GOAL-STATUS: BLOCKED — <원인>`, 턴마다 `GOAL-TURN k/40`, 40턴 초과 시 `GOAL-STATUS: STOPPED — <남은 모듈>`(둘 다 종료로 인정).
```

### Codex 변형

바뀐 점은 네 가지다.

- 정본 계획 파일을 참조한다. Codex 는 작업 모델이 스스로 감사하므로 파일을 읽는다.
- `[증거 규칙]` 을 `[보고]` (요구사항별 증거 한 줄)로 줄였다.
- 턴 상한 절(`GOAL-TURN`, `STOPPED`)을 없앴다. "멈추는 것은 완료가 아니다" 라는 continuation 규칙과 충돌하기 때문이다. 대신 token budget 을 goal 밖에서 건다. 예: 대화로 "이 objective 로 goal 을 만들고 token budget 은 3,000,000".
- blocked 는 Codex 규칙(같은 원인으로 3턴 연속)에 맞췄다.

좋은 예 (Codex, 902자):

<!-- goal: codex -->
```text
/goal [목표] `app/` 전체를 Pydantic v2 API로 옮기고 v1 호환층 사용을 없앤다. 범위·순서의 정본은 `docs/plans/pydantic-v2.md` — 먼저 읽고, 진행 체크리스트를 그 파일에 갱신한다.
[완료 조건] 현재 worktree 기준으로 모두 참일 때만 update_goal complete:
C1. 설치 버전 — 확인: `python -c "import pydantic; print(pydantic.VERSION)"` → `2.`로 시작.
C2. v1 API 잔존 0건 — 확인: `grep -rnE "pydantic\.v1|@validator\(|@root_validator\(|\.parse_obj\(|class Config:" app/ | wc -l` → `0`.
C3. 테스트 — 확인: `pytest -q` exit 0, passed 수 ≥ 시작 시 기록한 기준선.
C4. 타입 — 확인: `mypy app/` → `Success`.
C5. 억제 주석 추가 없음 — 확인: `git diff -U0 | grep -cE "^\+.*(type: ignore|noqa)"` → `0`.
C6. 계획 파일의 체크 항목이 모두 [x]다(v1 을 강제하는 서드파티 모듈은 사유와 함께 목록에 두고 [x]) — 확인: `grep -c '^- \[ \]' docs/plans/pydantic-v2.md` → `0`.
[제약] 공개 API 응답 JSON 형식 변경 금지. 테스트 기대값 수정 금지. 의존성은 pydantic·pydantic-settings만 변경.
[막힘·중단] 서드파티가 v1을 강제하는 모듈은 계획 파일 목록에 남기고 나머지를 계속한다. 같은 원인으로 3턴 연속 진전이 없을 때만 blocked.
[보고] 완료 시 C1–C6 각각을 증명하는 명령과 출력 한 줄을 적는다.
```
