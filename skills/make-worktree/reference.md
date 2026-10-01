# make-worktree 참고

SKILL.md 의 절차 뒤에 있는 배경이다. 실험 번호(E1~E11)는 Git for Windows 2.55 에서 임시 저장소로 확인한 결과다.

## 1. worktree · subtree · clone

| 도구 | 한 줄 정의 | 병렬 작업 폴더로 |
| --- | --- | --- |
| `git worktree` | 저장소 하나(`.git` 하나)에 작업 폴더를 여러 개 붙인다. 폴더마다 HEAD·index·파일은 따로, 커밋·브랜치·설정은 공유 | **맞다** — 이 스킬 |
| 다중 `clone` | 저장소를 폴더마다 통째로 복제 | 된다. 대신 서로의 브랜치를 모르고(원격 경유), `.git` 이 폴더마다 있다. 이미 있는 clone 은 이 스킬이 관리하지 않는다 |
| `git subtree` | 다른 저장소를 하위 폴더로 들여오고(add/merge/pull) 떼어 낸다(split/push) | **아니다** — 작업 폴더가 늘지 않고 다른 저장소 이력이 섞인다 |
| `git submodule` | 다른 저장소의 커밋을 gitlink 로 끼운다 | 아니다 |

비유: worktree 는 공책 한 권에 책갈피를 여러 개 꽂는 것, clone 은 공책을 복사하는 것, subtree 는 다른 공책의 한 장을 오려 붙이는 것이다. 사용자가 "서브트리" 라고 말해도 뜻은 병렬 작업 폴더이므로 `git subtree` 를 실행하지 않는다.

## 2. worktree 끼리 공유되는 것

| 공유된다 | 따로다 |
| --- | --- |
| 커밋·브랜치·태그, `origin/*` (fetch 한 번이면 모두 최신) | HEAD, index, 작업 트리 |
| **stash** (E2) — worktree 에서 stash 하면 메인에서 보인다 | ignored 파일(`.env`, `node_modules`, 빌드 결과) — 복사·설치해야 한다 |
| hooks(`.git/hooks`)와 config (E3) | `CLAUDE.local.md` 같은 로컬 문서 (그래서 복사한다) |
| Claude Code auto memory (저장소 단위) | 떠 있는 dev 서버·포트 |

- **같은 브랜치를 두 곳에서 checkout 할 수 없다 (E1)**: `fatal: 'main' is already used by worktree at …`. 그래서 base 는 detached(`switch --detach origin/main`)로 다룬다.
- **다른 worktree 가 checkout 한 브랜치는 git 이 움직이지 않는다 (E10)**: `branch -f`, `fetch . x:main` 이 거부된다. local 모드가 이 보호에 기대어 바쁜 메인의 브랜치를 건드리지 않는다.
- 커밋은 만드는 즉시 모든 worktree 에 보이므로 push 없이도 로컬 병합이 된다.

## 3. Windows 함정

| 함정 | 대응 |
| --- | --- |
| `git worktree remove` 가 ignored 파일(`.env`, `node_modules`)을 **경고 없이** 지운다 (E5) | 복사할 때 sha256 을 상태 파일에 적고, remove 전에 바뀐 것·새로 생긴 설정을 `<repo>.wt/.backup/<slug>-<시각>/` 로 백업한다 |
| worktree 안의 junction 을 둔 채 지우면 대상은 남지만 **좀비 폴더**가 남는다 (E7). pnpm 은 `node_modules` 를 junction 으로 만든다 | remove 가 junction·symlink 를 먼저 해제한다 (따라 들어가지 않는다 — `os.walk` 는 junction 을 따라가므로 직접 걷는다). 저장소가 추적하는 symlink(mode 120000)는 git 이 지우도록 남긴다 (먼저 지우면 dirty 가 되어 remove 가 거부된다). 그래도 폴더가 남으면 종료 코드 4 와 남은 경로를 알린다. `worktree.symlinkDirectories` 로 의존성을 공유하지 않는다 |
| 경로 길이 260자 (E11). `.claude\worktrees\<이름>` 은 약 38자를 더한다 | 형제 폴더 `<repo>.wt\<slug>` 와 짧은 slug. new 가 가장 긴 파일 경로를 계산해 240자를 넘으면 경고한다 |
| worktree 의 `.git` 포인터는 절대 경로다 | 폴더를 옮기면 `git worktree repair`. `worktree.useRelativePaths` 는 이를 모르는 구버전 git 이 저장소 전체를 못 열 수 있어 쓰지 않는다 |
| 임시 폴더·scratchpad 의 worktree 는 지워진 뒤 prunable 메타데이터로 남는다 | 위치는 항상 `<repo>.wt/<slug>`. status 가 `PRUNABLE` 을 보이고 remove·clean 이 정리한다 |
| 실행 중인 프로세스의 cwd 와 열린 파일은 지울 수 없다 | remove 는 자기 cwd 가 그 안이면 거부한다. 그 폴더에서 **시작한** Claude 세션·dev 서버·터미널은 먼저 끈다. 세션을 그 안에서 시작했다면 나중에 메인 폴더에서 remove·clean |
| `/w/works/...`(Git Bash) 와 `W:/works/...` 불일치 | 스크립트는 `git -C` 와 `--path-format=absolute` + `realpath`/`normcase` 로 비교한다 |
| `python3` 는 스토어 스텁, 콘솔은 cp949 | `python` 으로 실행한다. 스크립트는 stdout 을 UTF-8 로 바꾸고 subprocess 를 UTF-8 로 읽는다 |
| 브랜치 이름의 `#` 은 셸 주석이다 | 사람이 복사할 명령에서는 브랜치 이름을 항상 따옴표로 감싼다 |
| `wt` 명령줄의 `;` 는 하위 명령 구분자다 | 탭 제목·세션 이름에 `;`·`#` 을 넣지 않는다 |
| pnpm 은 애플리케이션 제어 정책에 막힐 수 있다 | `corepack pnpm install --frozen-lockfile --prefer-offline`. pnpm 은 hardlink 저장소라 worktree 마다 설치해도 싸다 |

## 4. Claude Code 와 함께 쓰기

- **`EnterWorktree(path=…)`** 는 이미 있는 worktree 로 지금 세션을 옮긴다. 시작 폴더에서 처음 들어갈 때는 그 경로가 현재 저장소(또는 시작 폴더 안의 중첩 저장소)의 `git worktree list` 에 있어야 한다 — `<repo>.wt/<slug>` 는 그 조건을 만족한다. `.claude/worktrees/` 밖이라 승인 프롬프트가 뜰 수 있다 (bypass 모드는 생략).
- 이미 worktree 세션 안이면 path 전환은 `.claude/worktrees/` 아래만 된다. 다른 make-worktree 폴더로 가려면 `ExitWorktree(action: "keep")` 후 다시 `EnterWorktree(path=…)`.
- **`ExitWorktree`** 는 EnterWorktree 가 이 세션에서 *만든* worktree 만 지운다. path 로 들어간 것은 `keep` 으로 나오기만 하고, 지우는 것은 `wt.py remove` 다.
- EnterWorktree 로 들어간 세션에는 "worktree 밖 편집 차단" 이 걸린다. 폴더에서 그냥 `claude` 로 연 세션에는 걸리지 않는다.
- **`claude -w <이름>` / `--worktree`** 는 `.claude/worktrees/<이름>` 에 브랜치 `worktree-<이름>` 으로 만든다. dev 서버가 필요 없는 짧은 일, PR 검토(`claude -w "#123"`)에는 이쪽이 간편하다. 쓰려면 `.claude/worktrees/` 를 `.gitignore`(또는 `.git/info/exclude`)에 넣는다. make-worktree 와 경쟁하지 않는다.
- **`.worktreeinclude`** (gitignore 문법, ignored 파일만) 는 Claude Code(`-w`, subagent 격리)와 이 스킬이 같은 파일을 읽는다. 있으면 이 스킬의 기본 목록 대신 쓴다. 예시는 `templates/worktreeinclude.example`.
- Windows 에서는 권한 승인이 worktree 쪽 `.claude/settings.local.json` 에 남는다. 그래서 기본 목록이 메인의 것을 복사한다.
- `<repo>.wt/<slug>` 는 메인 폴더 아래가 아니므로 메인의 `CLAUDE.local.md` 가 상위 폴더로 읽히지 않는다 → 복사한다. 메인과 `<repo>.wt` 의 공통 부모에 있는 CLAUDE.md/AGENTS.md 는 양쪽에서 읽힌다.
- linked worktree 안에서 `claude --bg` 를 쓰면 배경 세션이 또 worktree 를 만들지 않고 그 폴더를 그대로 쓴다.

## 5. 병합 방식 결정표

`finish`(모드 없이)와 `status` 가 아래 순서로 추천한다. 정하는 것은 사용자다.

| 순서 | 신호 | 추천 |
| --- | --- | --- |
| 1 | CLAUDE.md·AGENTS.md·CONTRIBUTING(상위 2단계 폴더의 CLAUDE.md·AGENTS.md 포함)에 병합 스크립트(`finish-task`, `relay-hub`, "병합 스크립트")가 있다 | `delegate` — 그 절차를 안내하고 멈춘다 |
| 2 | origin 이 없다 | `local` |
| 3 | origin 이 GitHub 이 아니다 | 문서가 PR 을 언급하면 `delegate`, 아니면 `push` |
| 4 | base 보호(`gh api repos/{o}/{r}/branches/{b}/protection` 200 또는 ruleset 의 `pull_request`), PR 템플릿·문서의 PR 언급, 저장소 소유자 ≠ gh 사용자 중 하나라도 | `pr` (gh 로그인이 없으면 그 사실을 함께 알린다) |
| 5 | gh 를 쓸 수 없다 | `push` (협업 저장소면 pr 을 고르라고 알린다) |
| 6 | 그 밖 — 개인 저장소, 보호·PR 규칙 없음 | `push` |

- 문서의 "PR 없음·금지" 같은 부정 문장은 PR 신호로 세지 않고 이유에만 보인다. 근거는 `파일:줄: 내용` 으로 보여 주므로 사람이 확인한다.
- 메인이 dirty 이거나 base 가 다른 폴더에 checkout 돼 있으면 local 모드는 그 폴더를 건드리지 않고 한 줄 안내로 끝난다.
- 모양은 merge commit(`--no-ff`)이다. 첫 부모가 base 라 이력이 읽기 쉽고, `branch -d` 가 머지를 알아본다. squash 는 `-d` 가 못 알아보므로 PR 상태(MERGED)로만 판단한다. rebase 는 push 하지 않은 브랜치에서 sync 할 때만 쓴다.
- 충돌은 worktree 안에서 base 를 merge 해서 푼다. 메인 폴더에서는 풀지 않는다.
- push 모드가 거절되면 fetch 후 한 번만 다시 병합·push 한다. 그 병합은 새 원격 커밋과의 조합이라 로컬에서 검증되지 않았다고 경고한다. 보호 규칙의 거부(GH006 등)는 재시도하지 않는다.

## 6. 상태 파일과 판정 규칙

`git -C <worktree> rev-parse --git-path make-worktree.json` = `<메인>/.git/worktrees/<id>/make-worktree.json`. 작업 트리에 보이지 않고 worktree 를 지우면 함께 사라진다.

```json
{
  "tool": "make-worktree", "version": 1, "slug": "login-fix", "branch": "wt/login-fix",
  "base": "origin/main", "base_branch": "main", "remote": "origin", "base_commit": "<sha>",
  "created_at": "2026-09-30T18:00:00+09:00", "port_offset": 1, "ports": {"vite": 5183},
  "main": "<메인 경로>", "copied": [{"path": ".env", "sha256": "<hex>", "size": 12}],
  "finish": {"mode": "push", "at": "…", "merge_commit": "<sha>"}
}
```

- **merged** = 만든 뒤 커밋이 1개 이상 있고 그 브랜치가 `origin/<base>`(원격이 없으면 로컬 base)에 들어갔다, 또는 gh 가 PR 을 MERGED 로 보고하고 로컬에 그 뒤 커밋이 없다. 커밋 없는 새 폴더는 merged 가 아니어서 clean 이 지우지 않는다.
- **UNPUSHED n** = 어느 원격 브랜치에도, base 에도 없는 커밋 수 (원격이 없으면 다른 로컬 브랜치에 없는 커밋 수). remove 는 이 수가 0 이 아니고 merged 도 아니면 거부한다.
- **포트 오프셋** = 다른 make-worktree 폴더가 쓰지 않는 가장 작은 양의 정수. 제안 포트 = 기본 포트(vite 5173, web 3000, api 8000, spring 8080 중 감지된 것, 감지 못 하면 넷 다) + 오프셋×10. 8000·8001(로컬 서버·업로드 창구)은 피한다.
- `new` 는 공용 `.git` 의 잠금 파일(`make-worktree.lock`)로 오프셋 배정과 `worktree add` 를 한 번에 하나씩 한다.
- 메인 쪽에서 실행하는 git 명령은 refs·config·`.git/worktrees` 만 바꾼다: `fetch --no-write-fetch-head`(메인의 `git pull` 과 FETCH_HEAD 경합 방지), `worktree add/remove/prune`, `branch -d`. `git status` 는 `GIT_OPTIONAL_LOCKS=0` 으로 index 를 다시 쓰지 않는다.
- 브랜치 삭제: `git branch -d` 는 upstream 이 없으면 **현재 HEAD** 기준으로 머지를 판단하는데, 바쁜 메인의 HEAD 는 낡았을 수 있다. 그래서 upstream 이 없는 브랜치는 잠시 upstream 을 `origin/<base>` 로 잡고 `-d` 한다 (실패하면 되돌린다).

## 7. 설계 결정

- **작업별 일회용 폴더**: 번호 슬롯을 재사용하지 않고 작업마다 `<repo>.wt/<slug>` 를 만들고 머지 뒤 지운다 (사용자 결정). 폴더 이름이 작업을 말해 주고 잔재가 쌓이지 않는다. 대신 의존성은 매번 설치한다 (pnpm 은 hardlink 라 싸다).
- **병합은 worktree 안에서**: 바쁜 메인에 checkout 된 base 를 움직이지 않으려고 detached HEAD 에서 `merge --no-ff` 를 만들어 `HEAD:refs/heads/<base>` 로 push 한다. 메인은 나중에 `git pull --ff-only` 만 하면 된다.
- **stash 를 쓰지 않는다**: 모든 worktree 가 stash 를 공유해서(E2) 다른 세션의 stash 를 꺼낼 수 있다.
- **방식은 매번 묻는다**: 같은 저장소라도 보호 규칙·협업자·작업 성격에 따라 PR 과 직접 push 가 갈린다. 저장하지 않고 신호로 추천만 한다.
