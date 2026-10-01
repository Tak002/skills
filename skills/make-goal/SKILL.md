---
name: make-goal
description: 이루고 싶은 것을 자유 문장으로 받아 Claude Code /goal 조건문 또는 Codex goal objective 로 바꾼다. 프로젝트에서 테스트·빌드·타입체크 명령과 보호 경로를 읽어 "끝난 상태 + 확인 명령 → 기대값 + 게이밍 차단 제약 + BLOCKED/STOPPED 종료 절" 골격을 채우고, scripts/check_goal.py 로 길이(기본 4,000자. Claude 는 UTF-16, Codex 는 문자 수)와 형식을 검사해 넘치거나 틀리면 고쳐서 다시 검사하며, 그래도 넘치면 런처 goal + 명세 파일로 나눈다. 옵션 --target claude|codex|both, --limit N (OpenChamber 는 5000), --turns N, --out 경로. "goal 만들어줘", "/goal 프롬프트 작성", "goal 프롬프트로 바꿔줘", "make-goal", "codex goal objective 만들어줘", "목표 조건 만들어줘", "이 작업 goal 로 돌리게 조건 써줘" 같은 요청에 사용.
---

# make-goal

이루고 싶은 것을 받아, 붙여 넣으면 바로 도는 goal 을 만든다. goal 은 "끝난 상태 + 확인 명령 → 기대값 + 게이밍 차단 제약 + 막힘·중단 규칙" 으로 된 짧은 계약문이다. 만든 뒤 `scripts/check_goal.py` 로 길이와 형식을 검사하고, 오류가 있으면 고쳐서 다시 검사한다.

- **길이 제한은 Claude Code `/goal` 과 Codex objective 모두 4,000자다.** Claude 는 UTF-16 길이(이모지 2), Codex 는 문자 수(이모지 1)로 센다. 5,000자는 OpenChamber 의 제한이다. 사용자가 "5,000자" 라고 해도 Claude·Codex 용이면 한 줄로 바로잡고 4,000 으로 맞춘다. OpenChamber 용이면 `--limit 5000`.
- Claude Code 의 완료 판정자는 **도구 없는 별도 Haiku** 이고 transcript(뒤쪽 약 100k 토큰, 큰 출력은 앞 2KB)만 본다. 파일을 못 읽으므로 판정 기준은 goal 본문에, 증거는 마지막 턴의 출력에 있어야 한다. Codex 는 작업 모델이 스스로 감사한다.
- 요구 사항: Python 3.10+ (표준 라이브러리만). Windows 에서 `python3` 가 Microsoft Store 스텁이면 `python` 을 쓴다.

`<skill>` 은 이 SKILL.md 가 있는 폴더의 실제 경로다.

## 입력

인자: $ARGUMENTS

인자가 비어 있으면 사용자의 요청 문장을 쓴다. 자유 문장 = 이루고 싶은 것. 옵션:

| 옵션 | 기본값 | 뜻 |
| --- | --- | --- |
| `--target claude\|codex\|both` | `claude` | 어느 제품용인지. `both` 면 두 벌 |
| `--limit N` | `4000` | 하드 제한. OpenChamber 는 `5000` |
| `--turns N` | 유형별 (3단계) | Claude STOPPED 절의 턴 상한 |
| `--out <경로>` | 없음 | 최종 goal(코드 블록 내용 그대로, `/goal ` 포함)을 파일로도 저장. `both` 면 `<이름>.claude<확장자>`, `<이름>.codex<확장자>` |

## 실행 절차

1. **프로젝트에서 추론한다.** 묻기 전에 먼저 읽는다.
   - 명령: `package.json` scripts(test·typecheck·lint·build·e2e)와 lockfile 로 정한 패키지 매니저, `build.gradle*`/`gradlew`, `pom.xml`, `pyproject.toml`(pytest·mypy·ruff, uv·poetry), `Makefile` 타깃, `Cargo.toml`, `go.mod`.
   - 규칙: `CLAUDE.md`·`AGENTS.md` 의 금지 사항, 보호 경로, 커밋 정책, 보고서 폴더 규칙.
   - 셸: Claude Code Bash 도구(Windows 는 Git Bash)면 `echo "EXIT=${PIPESTATUS[0]}"`, PowerShell 이면 `"EXIT=$LASTEXITCODE"`. Codex on Windows 는 PowerShell 이 기본이다.
   - 보호 경로 후보: 기존 테스트·스냅샷, 테스트·커버리지·lint 설정, 마이그레이션, lockfile.
   - 기존 명세: `docs/specs`, `docs/plans`, `PLAN.md`, 보고서 폴더.
   - 프로젝트 파일이 없으면 요청에 나온 정보와 흔한 기본값으로 쓰고 "가정" 에 적는다.

2. **묻는 것은 한 번까지.** 완료를 확인할 방법을 전혀 만들 수 없을 때만(확인할 명령·산출물이 없고 "좋게 만들어" 뿐) 질문을 한 번에 묶어 묻는다. 그 밖에는 기본값을 고르고 goal 밖 "가정" 에 적는다. 한 번에 끝나는 일, 디자인 판단, 중간에 사람 결정이 필요한 일, 결과가 여러 개 섞인 일이면 goal 대신 일반 프롬프트·`/plan`·순차 goal 을 권한다 (reference.md 11절).

3. **유형을 고른다.** bugfix · feature · refactor · research(보고서) · coverage · migration · docs · other. `--turns` 가 없으면 턴 상한은 bugfix 25, feature 30, refactor 40, research 20, coverage 30, migration 40, docs 20, other 25.

4. **초안을 쓴다.** 먼저 [reference.md](reference.md) 의 3절(템플릿·길이 예산), 4절(제품별 조정), 6절(유형별 게이밍 차단 제약)을 읽는다. 좋은 예는 [examples.md](examples.md). 골격:

   ```text
   [목표] 끝난 상태 한 문장 (대상 경로·모듈·이슈 포함)
   [완료 조건] 아래 C1–Cn이 모두 참일 때만 완료로 본다.
   C1. 관찰 가능한 상태 — 확인: `명령 2>&1 | tail -n 15; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`
   C2. … — 확인: `명령` → 기대값 (`0`, `≥ N`, `1 passed`, 문자열)
   [증거 규칙] 완료를 주장하는 턴에서 C1–Cn 명령을 다시 실행해 출력이 tool 결과에 남게 한다. 최종 메시지에 `C1 ✅ <근거 원문 한 줄>` 체크리스트. 이전 턴의 기억은 증거가 아니다.
   [제약] (위반하면 미완료) 보호 경로·약화 금지 … 확인: `git diff --stat -- 보호 경로` 출력이 비어 있음.
   [범위 밖] 하지 않을 일
   [막힘·중단] 사용자에게 묻지 않는다. 명세에 없는 결정은 기본값으로 하고 최종 메시지 "결정 기록" 에 남긴다. 같은 원인으로 3번 연속 실패하면 `GOAL-STATUS: BLOCKED — <원인>`. 턴마다 `GOAL-TURN k/N`, N턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>`. 둘 다 종료로 인정한다.
   [참고] (판정 대상 아님) 명세·관련 파일 경로
   ```

   - C 는 3–7개. 항목마다 "상태 — 확인: `명령` → 기대값". "통과한다" 로 끝내지 않는다. 테스트는 전체 명령·최소 개수·시작 시 기준선으로 사소하게 참이 되는 것을 막는다.
   - 유형별 게이밍 차단 제약을 넣고, 제약에도 확인 명령을 붙인다 (reference.md 6절).
   - 주관 표현(깔끔, 잘, 적절, 충분, 최적, 완벽, 개선, production-ready, 가능한 한)과 사람의 행동(승인·머지)에 기대는 조건을 쓰지 않는다.
   - `[목표]` 와 `[완료 조건]` 첫 줄을 앞 500자 안에 둔다.
   - **Codex 꼬리**: `[완료 조건]` 머리를 "현재 worktree 기준으로 모두 참일 때만 update_goal complete:" 로, `[증거 규칙]` 대신 `[보고]`(C 항목마다 증명 명령과 출력 한 줄)로 쓴다. **턴 상한·`GOAL-TURN`·`STOPPED` 절을 넣지 않는다.** blocked 는 "같은 원인으로 3턴 연속 진전이 없을 때만". 예산은 goal 밖에서 token budget 으로 안내한다. 명세 파일은 참조해도 된다(모델이 읽는다).
   - `both` 면 공통 코어는 같게 두고 꼬리만 다른 두 벌을 만든다.

5. **검사 루프 (최대 5회).** 초안을 임시 파일(세션 스크래치패드나 OS 임시 폴더. 프로젝트 안은 피한다)에 쓰고 검사한다. 결과에 따라 고치고 다시 검사한다.

   ```bash
   python <skill>/scripts/check_goal.py <초안 파일> --target claude --shell bash         # --shell = goal 의 명령을 돌릴 셸
   python <skill>/scripts/check_goal.py <초안 파일> --target codex --shell powershell    # both 면 두 벌을 각각 검사
   ```

   - 종료 코드 0 = 통과(경고만), 1 = 오류, 2 = 사용법 오류. 첫 줄은 `길이: N / 4,000자 (claude, UTF-16 기준) · 검사 통과|실패` 이고 섹션별 길이가 따라 나온다. `--limit N`, `--json` 도 된다.
   - **오류는 반드시 고친다**: 길이 초과, 필수 섹션 누락(`[목표]` `[완료 조건]` `[제약]` `[막힘·중단]`, Claude 는 `[증거 규칙]`), C 항목 없음, `확인` 이 없는 C 항목, 남은 `{…}` 자리표시, Claude 의 `GOAL-STATUS` 절 누락.
   - **경고**(3,500자 초과, 앞 500자, 명령·기대값 없는 C, 판정자가 못 읽는 파일 기준, 주관 표현, Codex 턴 상한 절, 셸 관용구, 확인 없는 금지 조항 등)는 고치거나, 남기면 이유를 "가정" 에 적는다. 규칙 표는 reference.md 8절.
   - **길이를 넘으면 압축 사다리를 위에서부터 한 칸씩** 적용하고 다시 검사한다 (자세히는 reference.md 7절):
     1. `[참고]` 를 지우거나 줄인다 (판정 대상이 아니므로 먼저).
     2. `[범위 밖]` 을 명사 나열 한 줄로 줄인다.
     3. 문장을 압축한다. 조사·수식어·괄호 설명을 빼고, `tail -n 20` 을 `tail -n 5` 로 줄이고, C 마다 반복되는 `2>&1 | tail … EXIT=` 는 `[증거 규칙]` 의 공통 규칙 한 줄로 옮긴다.
     4. 겹치는 C 항목을 합친다. 3개 미만으로 줄이지 않고 확인 명령을 잃지 않는다.
     5. 배경·절차 문장을 명세 파일로 옮긴다.
   - 사다리를 다 써도 넘치면 6단계로 간다. 첫 초안이 제한의 1.5배 이상이면 사다리를 건너뛰고 바로 간다.

6. **런처 + 명세로 나눈다** (reference.md 5절).
   - 명세 경로는 프로젝트 안에 정한다. 보고서 폴더 규칙이 있으면 그대로 따르고, 없으면 `docs/goals/YYYY-MM-DD-<slug>.md` 다.
   - 명세에는 배경, 인벤토리(`- [ ] R1. …` 체크리스트), 절차, 결정 기록 표를 쓴다.
   - 런처(목표 3,500자 이하)에는 `[목표]`, `[완료 조건]`, `[증거 규칙]`, `[제약]`, `[막힘·중단]` 을 모두 인라인으로 둔다.
   - Claude 판정자는 명세를 못 읽는다. 런처의 C 항목은 명세 체크리스트를 출력으로 확인하게 쓴다. 예: `grep -c '^- \[ \]' <명세>` → `0`. **"명세대로 수행" 만으로 완료를 판정하게 두지 않는다.**
   - 명세는 작업 중에 갱신되므로 보호 경로 검사에서 뺀다.
   - 명세를 쓰고 런처를 다시 검사한다.

7. **출력한다.** 순서대로 쓴다.
   1. 최종 goal 을 코드 블록 하나로 쓴다. Claude 는 `/goal ` 로 시작하고 여러 줄이어도 된다. Codex 도 TUI 에 붙일 `/goal ` 형태다. `both` 면 블록 두 개다.
   2. 길이 줄 (goal 마다): `길이: 3,120 / 4,000자 (claude, UTF-16 기준) · 검사 통과 · 반복 2회`. 앞부분은 check_goal.py 첫 줄 그대로, 반복은 검사를 돌린 횟수다. 통과하지 못했으면 `검사 실패` 와 남은 오류를 그대로 적는다.
   3. goal 밖에 쓸 것:
      - 가정 (고른 기본값, 남긴 경고와 이유)
      - 실행 전 체크 (reference.md 10절: 권한·기준선·보호 경로 추적·턴 또는 예산)
      - 권한에 미리 허용할 명령 (`Bash(pnpm test:*)` 형식)
      - Codex 면 token budget 제안
   4. 런처로 나눴으면 명세 파일 경로를, `--out` 이면 저장 경로를 알린다.

## 주의

- 검사를 통과하지 못한 goal 을 통과한 것처럼 내놓지 않는다. 검사를 돌릴 수 없는 환경(명령 실행 금지, plan 모드)이면 그렇게 말하고, 규칙 표(reference.md 8절)로 한 번 대조하고, 길이는 섹션별로 어림해 더한 추정치라고 적는다. ±10% 면 충분하니 한 글자씩 세지 않는다. 어림값이 제한의 90% 를 넘으면 사다리를 한 칸 더 적용한다.
- goal 문구는 권한 경계가 아니다. push·배포·삭제는 settings deny·sandbox 로 막으라고 안내한다.
- Codex 에 "N턴 뒤 중단" 을 넣지 않는다 (continuation 규칙 "멈추는 것은 완료가 아니다" 와 충돌). 사용자가 요청하지 않은 token budget 을 goal 에 넣지 않는다.
- goal 에 비밀값·개인 정보를 넣지 않는다.

## 참고

- [reference.md](reference.md): 제품별 메커니즘과 길이 제한 표, 원칙 P1–P15, 템플릿과 섹션 길이 예산, 제품별 조정, 런처 + 명세, 유형별 게이밍 차단 제약, 압축 사다리, check_goal.py 규칙 표, 안티패턴 체크리스트, 실행 전 체크, goal 을 쓰지 말아야 할 때.
- [examples.md](examples.md): 나쁜 goal → 좋은 goal 6종과 Codex 변형.
- `python <skill>/scripts/check_goal.py --help`. 테스트: `python -m unittest discover -s <skill>/tests -q`.
