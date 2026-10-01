# make-worktree 평가 결과

문제지: `evals.json` (3문제, 기준 12개). 실행: `python workspace/run_evals.py --skill make-worktree`.

## 기록

| iteration | 날짜 | with-skill | baseline | delta | 메모 |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-01 | 11/11 (100%) | 5/11 (45.5%) | +54.5 | 격리 실행. 문제별 4/4·4/4·3/3 vs 2/4·0/4·3/3 (문제 3 은 기준 3개) |
| 2 | 2026-10-01 | 12/12 (100%) | 6/12 (50.0%) | +50.0 | 문제 3 에 백업 기준 추가(기준 11→12), SKILL.md 에 status 플래그 뜻 추가. 문제별 4/4·4/4·4/4 vs 2/4·1/4·3/4 |

## 실행 검증 (실제 저장소, 문제지 밖)

평가와 단위 테스트가 못 덮는 "세션을 `<repo>.wt/<slug>` 로 옮기기" 를 이 저장소(`skills`)에서 실제로 돌렸다 (2026-10-01, Claude Code 2.1.285). push 는 하지 않았다.

1. `wt.py new wt-smoke` → `skills.wt\wt-smoke`, 브랜치 `wt/wt-smoke`, base `origin/main`, 포트 오프셋 1. 메인(미커밋 변경 15건)은 그대로.
2. `EnterWorktree(path=…\skills.wt\wt-smoke)` → **성공.** 저장소 밖 형제 폴더도 `git worktree list` 에 있으면 들어간다. 세션 작업 폴더가 바뀌고 대화 맥락이 유지된다.
3. worktree 안에서 커밋 1개 → `sync` "이미 최신" → `finish`(방식 없음) 은 점검 통과와 신호(GitHub, 소유자 = gh 사용자, 보호 없음, 문서 PR 언급 없음, 메인 dirty 15)를 보여 주고 `push` 를 추천했다. 아무것도 바꾸지 않았다.
4. `finish --mode push --dry-run` → `switch --detach origin/main` → `merge --no-ff` → `push origin HEAD:refs/heads/main` 순서를 출력.
5. `ExitWorktree(action: "keep")` → 원래 폴더로 복귀, worktree 는 남음.
6. `remove wt-smoke --delete-branch` → **거부** ("원격에도 base 에도 없는 커밋 1개"). 의도대로다. 시험 브랜치라 `remove --force`(폴더만) 뒤 `git branch -D` 로 정리했고, 빈 `skills.wt` 도 지워졌다.

## 발견과 조치

- **iteration 1 의 문제 3(상태 보고 정리) 은 baseline 도 3/3** 이었다. "dry-run 먼저", "머지된 것만 지운다" 는 일반 지식으로도 맞히는 기준이라 변별력이 없었다. → 스킬 고유 기준 "지우기 전에 바뀐 .env 같은 ignored 설정을 백업한다 (`git worktree remove` 는 ignored 파일을 경고 없이 지운다, 실험 E5)" 를 더했다. iteration 2 에서 baseline 은 "--force 없이 지우면 변경이 남아 있을 때 git 이 알아서 거부한다" 고 답해 정확히 이 함정에 빠졌고(FAIL), with-skill 은 백업 경로까지 말했다(PASS).
- **문제 2(합쳐줘) 가 가장 크게 갈린다.** baseline 은 두 번 다 메인 폴더에서 `git -C <메인> switch main` + `merge --no-ff` 를 하겠다고 했고, 충돌도 메인에서 풀며, 방식은 `git log` 의 관례로만 골랐다 (0/4, 1/4). with-skill 은 worktree 안에서 sync → 검증 → 신호로 추천하고 묻기 → finish 순서를 지켰다.
- **문제 1(subtree 만들어줘) 에서 baseline 2/4**: "subtree 가 아니라 worktree", "메인을 건드리지 않는다" 는 스스로 맞혔지만, 경로를 `..\<repo>-login-fix` 로 잡았고 EnterWorktree 로 세션을 옮기는 것을 몰랐다.
- with-skill 은 두 번 다 만점이라 SKILL.md 문장 때문에 떨어진 칸은 없다. 다만 iteration 1 의 문제 3 응답이 `CWD` 플래그를 "어떤 프로세스가 그 폴더에서 실행 중" 으로 잘못 풀었다 → SKILL.md status 절에 플래그마다 뜻을 적었고, iteration 2 응답은 "셸이 그 폴더 안에 있음" 으로 바르게 썼다.
- 평가 대상 claude 는 git 저장소가 아닌 빈 임시 폴더에서 돌아서 with-skill 응답이 매번 "저장소 경로를 알려 달라 / `--repo`" 로 시작한다. 정상이다.
- 응답 시간: with-skill 29~54초, baseline 22~30초.
- 다음 문제 후보: 문서에 relay-hub `finish-task` 가 있는 저장소(delegate 판정), 세션을 worktree 안에서 시작해 remove 를 못 하는 경우, squash 머지된 PR 의 브랜치 정리.
