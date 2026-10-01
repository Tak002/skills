---
name: make-worktree
description: 메인 작업 폴더가 바쁠 때(커밋 안 된 변경, 돌고 있는 에이전트, 떠 있는 dev 서버) git worktree 로 메인 폴더 옆에 작업별 일회용 폴더 <repo>.wt/<slug> 를 만들고 지금 Claude 세션을 그리로 옮겨 작업한 뒤, base 동기화 → 검증 → 상황에 맞는 방식(PR·직접 push·로컬 병합)으로 합치고 지운다. 메인 체크아웃은 건드리지 않는다. new / status / sync / finish / remove / clean. 사용자가 "subtree"·"서브트리"라고 불러도 git subtree 가 아니라 이 스킬(git worktree)을 뜻한다. "병렬로 작업할 폴더 만들어줘", "worktree 만들어줘", "서브트리 만들어서 거기서 작업", "작업 끝났으니 합쳐줘", "worktree 정리", "병렬 작업 폴더 상태 보여줘" 같은 요청에 사용.
---

# make-worktree

메인 체크아웃이 바쁠 때 같은 저장소의 작업 폴더를 하나 더 열어(git worktree) 거기서 일하고, 끝나면 안전하게 합친 뒤 지운다. 폴더는 작업마다 새로 만들고 머지 뒤 지운다.

```text
<부모>/
├─ <repo>/            메인 체크아웃 — 읽기만 한다 (작업 트리·index·checkout 된 브랜치를 바꾸지 않음)
└─ <repo>.wt/
   ├─ <slug>/         작업 폴더. 브랜치 wt/<slug>, 시작점 = origin 기본 브랜치
   └─ .backup/        remove 때 worktree 에서 바뀐 .env 등을 백업
```

- "subtree" 라고 들어도 `git subtree` 를 실행하지 않는다. 이 스킬은 git worktree 다 (차이는 [reference.md](reference.md)).
- 스크립트: `python <skill>/scripts/wt.py <명령>`. `<skill>` 은 이 SKILL.md 가 있는 폴더다. Python 3.10+ 표준 라이브러리, git 2.31+. Windows 에서는 `python3`(스토어 스텁)가 아니라 `python`.
- 메인 = `git worktree list` 의 첫 항목. 어느 worktree 안에서 불러도 같은 메인과 같은 `<repo>.wt` 를 쓴다. 저장소 밖에서 부르면 `--repo <경로>`.
- 모든 명령에 `--json`. 종료 코드: **0** 성공 · **1** 오류 · **2** 거부(전제 조건·인자) · **3** 충돌 · **4** 정리 미완(폴더가 남음).

## 만들기 (new)

1. 작업 설명에서 짧은 영어 kebab-case slug 를 정한다. 30자 이하, 되도록 20자 이하 (Windows 경로 길이). 예: "로그인 버그 고칠 거야" → `login-fix`.
2. 실행한다. 메인 폴더에서 checkout·stash·commit·pull 을 하지 않는다.

   ```powershell
   python <skill>/scripts/wt.py new login-fix              # origin/HEAD(예 origin/main)에서 브랜치 "wt/login-fix"
   python <skill>/scripts/wt.py new login-fix --install    # 빌드·테스트가 필요한 작업이면 의존성까지 설치
   ```

   옵션: `--branch "<이름>"`, `--base <ref>`, `--from-head`(메인의 커밋된 HEAD 에서 — 미커밋 변경은 안 따라온다), `--no-fetch`, `--no-copy`. 원격이 없으면 메인 HEAD 에서 시작한다.
   하는 일: fetch → `git worktree add --no-track -b` → 메인의 ignored 로컬 설정 복사(`.worktreeinclude`, 없으면 `.env*`·`CLAUDE.local.md`·`.claude/settings.local.json`, 1MB 이하) → lockfile 로 설치 명령 감지(`--install` 이 없으면 출력만) → 포트 오프셋 배정. 마지막 줄은 `WORKTREE: <경로>`.
3. **지금 세션을 그 폴더로 옮겨 바로 작업한다.** `EnterWorktree` 도구를 `path` = WORKTREE 경로로 부른다. 대화 맥락을 유지한 채 이어서 작업한다.
   - 이미 다른 worktree 세션 안이면 먼저 `ExitWorktree(action: "keep")` 로 나온 뒤 부른다 (worktree 세션 안에서의 path 전환은 `.claude/worktrees/` 아래만 된다).
   - 도구가 없거나 거부되면 출력의 대안을 안내한다: 새 탭 `wt -w 0 nt -d "<경로>" pwsh -NoExit -Command claude`, `code -n "<경로>"`, 다른 에이전트·셸은 `cd "<경로>"`(또는 `git -C <경로>`).
4. 사용자에게 경로·브랜치·base·복사한 파일·설치 명령·포트를 알린다. dev 서버는 출력의 포트(기본 포트 + 오프셋×10, 8000·8001 제외)로 띄운다.

## 상태 (status)

```powershell
python <skill>/scripts/wt.py status          # make-worktree 폴더 + 저장소 신호 + finish 방식 추천
python <skill>/scripts/wt.py status --all    # 메인과 관리 밖 worktree 까지 (--fetch 면 먼저 fetch)
```

폴더마다 브랜치·dirty·ahead/behind·커밋 수·upstream·마지막 커밋·포트와 플래그를 보여 준다. 아무것도 바꾸지 않는다.
`MERGED→remove`(base 에 들어감, 지워도 됨) · `DIRTY`(커밋 안 된 변경) · `UNPUSHED n`(원격에도 base 에도 없는 커밋) · `BEHIND n`(base 가 앞서 있음 → sync) · `PRUNABLE`(폴더 없이 메타데이터만) · `CWD`(지금 이 명령을 부른 셸의 작업 폴더가 그 안) · `LOCAL-PENDING`(local 병합을 다른 폴더에서 기다림) · `PR #n OPEN`.

## 끝내기: sync → 검증 → 방식 선택 → finish → remove

모두 worktree 안에서 한다. 메인 폴더에서 merge·checkout·충돌 해결을 하지 않는다.

1. 작업을 커밋한다. 스크립트는 대신 커밋하지 않는다.
2. **sync** — base 의 새 커밋을 worktree 안으로 병합한다.

   ```powershell
   python <skill>/scripts/wt.py sync          # worktree 안에서. 밖이면 sync <slug>
   ```

   종료 코드 3 = 충돌. 나열된 파일을 worktree 안에서 고치고 `git add` → `git commit --no-edit` → sync 를 다시 실행한다. `--rebase` 는 push 안 한 브랜치에만.
3. **검증 (필수)** — 합치기 전에 테스트·빌드를 worktree 안에서 돌린다. 명령 찾는 순서: 저장소 문서(CLAUDE.md, AGENTS.md, CONTRIBUTING, README) → CI 설정(`.github/workflows/*.yml` 의 `run:`) → `package.json` scripts(test·build·lint·typecheck), Makefile, pyproject/pytest, `gradlew test`. 의존성이 없으면 new 가 출력한 설치 명령부터. 양쪽이 같은 화면·상태를 건드렸으면 dev 서버로 런타임 확인도 한다. 실패하면 고쳐서 커밋하고 2단계부터 다시.
4. **방식 선택** — `finish` 를 `--mode` 없이 실행하면 점검(clean·커밋 있음·동기화됨)과 신호, 추천만 보여 주고 아무것도 바꾸지 않는다. 신호는 origin 유무, GitHub·gh 로그인, base 브랜치 보호(protection 200·ruleset), 문서의 PR·병합 스크립트 언급, 저장소 소유자 = gh 사용자 여부, 메인 dirty 다. **추천과 이유를 보여 주고 사용자에게 방식을 묻는다** (사용자가 이미 말했으면 묻지 않는다). 매번 상황으로 정하고 기본값을 저장하지 않는다.

   | 방식 | 하는 일 | 뒤처리 |
   | --- | --- | --- |
   | `pr` | `push -u` + `gh pr create` | 머지되면 status 가 `MERGED→remove` → remove |
   | `push` | worktree 안에서 `switch --detach origin/<base>` → `merge --no-ff` → `push origin HEAD:refs/heads/<base>`. 거절되면 fetch 후 한 번만 재시도, 보호 규칙 거부면 멈추고 pr 을 권한다 | 바로 remove |
   | `local` | 원격 없음. base 가 다른 폴더(바쁜 메인)에 checkout 돼 있으면 건드리지 않고 그 폴더에서 실행할 한 줄만 안내한다. 아니면 worktree 안에서 병합하고 ref 를 옮긴다 | 합쳐진 뒤 remove |
   | `delegate` | 문서에 자체 병합 절차(예: relay-hub `finish-task`)가 있으면 그 절차를 안내하고 멈춘다 | 그 절차대로 |

5. **finish**

   ```powershell
   python <skill>/scripts/wt.py finish --mode push
   python <skill>/scripts/wt.py finish --mode pr --title "로그인 버그 수정" --body-file pr.md   # --dry-run 이면 명령만
   ```

   출력의 "메인 폴더" 줄(예: 한가할 때 `git pull --ff-only`)을 사용자에게 그대로 전한다.
6. 아래 "지우기" 로 정리한다 (pr 은 머지된 뒤).

## 지우기 (remove / clean)

1. 세션이 그 worktree 안에 있으면 먼저 `ExitWorktree(action: "keep")` 로 원래 폴더로 돌아온다. path 로 들어간 worktree 는 ExitWorktree 가 지우지 않으므로 그다음 스크립트로 지운다.

   ```powershell
   python <skill>/scripts/wt.py remove login-fix --delete-branch
   ```

   dirty 면 거부한다. 원격에도 base 에도 없는 커밋이 있으면 거부한다 — 사용자가 명시적으로 확인했을 때만 `--force`(폴더만 지우고 브랜치는 남긴다). 지울 때 바뀐 `.env` 등을 `<repo>.wt/.backup/<slug>-<시각>/` 에 백업하고, 안의 junction·symlink 를 먼저 해제하고, `git worktree remove`(force 없이) 뒤 폴더가 남았는지 확인하고, 머지된 브랜치만 `-d` 로 지운다 (squash 머지는 PR 이 MERGED 일 때만 `-D`).
2. 세션을 그 worktree 안에서 **시작**했다면(환경의 작업 폴더가 그 안) Windows 는 실행 중인 프로세스의 cwd 를 지우지 못한다. 지우지 말고 "나중에 메인 폴더에서 `remove <slug>` 또는 `clean`" 을 안내한다. status·clean 이 남은 것을 다시 찾는다.
3. 여러 개를 정리할 때는 dry-run 부터:

   ```powershell
   python <skill>/scripts/wt.py clean          # 목록만: 머지된 make-worktree 폴더, prune 대상, 빈 껍데기 폴더
   python <skill>/scripts/wt.py clean --yes    # 사용자에게 목록을 확인받은 뒤에만
   ```

   머지된 것만 remove 와 같은 방식(바뀐 설정 백업·링크 해제·`-d`)으로 지운다. dirty·cwd·잠긴 것은 건너뛴다.

## 지켜야 할 것

- 메인 체크아웃의 작업 트리·index·checkout 된 브랜치를 바꾸지 않는다. 메인에서 할 일은 "한가할 때 실행할 한 줄" 로만 안내한다.
- `--force`, `-f -f`, `git branch -D` 는 사용자가 명시적으로 확인한 뒤에만 쓴다.
- 인계에 stash 를 쓰지 않는다 (모든 worktree 가 stash 를 공유한다).
- 셸에 넘기는 브랜치 이름은 항상 따옴표로 감싼다 (`#` 이 주석으로 잘린다).
- worktree 를 임시 폴더·scratchpad 에 만들지 않는다 (prunable 메타데이터가 남는다). 위치는 항상 `<repo>.wt/<slug>` 다.
- 같은 브랜치는 두 worktree 에서 동시에 checkout 할 수 없다. base 브랜치는 detached 로 다룬다.
- 충돌은 worktree 안에서만 풀고, 합치기 전 검증을 건너뛰지 않는다.

## 참고

- [reference.md](reference.md): worktree·subtree·clone 비교, worktree 끼리 공유되는 것, Windows 함정, Claude Code 연동(EnterWorktree, `claude -w`, `.worktreeinclude`), 병합 방식 결정표, 상태 파일.
- `templates/worktreeinclude.example`: 메인 저장소 루트에 `.worktreeinclude` 로 두면 복사 목록을 바꾼다. Claude Code 도 같은 파일을 읽는다.
- 테스트: `python -m unittest discover -s <skill>/tests -q` (임시 폴더의 실제 git 저장소로).
