"""make-worktree scripts/wt.py 테스트. 임시 폴더에 진짜 git 저장소(bare origin + 바쁜 메인 clone)를 만들어 돌린다.

    python -m unittest discover -s skills/make-worktree/tests -q

- 사용자 git 설정의 영향을 받지 않게 GIT_CONFIG_NOSYSTEM + 빈 GIT_CONFIG_GLOBAL 로 격리한다.
- gh 는 부르지 않는다 (MAKE_WORKTREE_NO_GH=1). GitHub 에 push 하거나 PR 을 만들지 않는다.
- 메인 체크아웃은 일부러 dirty(수정·stage·untracked·ignored)로 두고, 명령 전후 스냅숏이 같은지 본다.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
WT_PY = os.path.join(SCRIPTS, "wt.py")
sys.path.insert(0, SCRIPTS)
import wt  # noqa: E402

for _s in (sys.stdout, sys.stderr):  # 실패 메시지의 한글이 cp949 콘솔에서 깨지지 않게
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _rmtree(path: str) -> None:
    def on_error(func, p, _exc):  # git 오브젝트는 Windows 에서 읽기 전용이다
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=on_error)
    else:
        shutil.rmtree(path, onerror=on_error)


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


class RepoCase(unittest.TestCase):
    """bare origin + seed(다른 사람 역할) + main(바쁜 메인 체크아웃)."""

    def setUp(self) -> None:
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="mwt-"))
        self.addCleanup(_rmtree, self.tmp)
        cfg = os.path.join(self.tmp, "gitconfig")
        open(cfg, "w").close()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": cfg,
            "GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "tester@example.com",
            "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "tester@example.com",
            "MAKE_WORKTREE_NO_GH": "1", "PYTHONIOENCODING": "utf-8",
        })
        self.env = env
        self.origin = os.path.join(self.tmp, "origin.git")
        self.seed = os.path.join(self.tmp, "seed")
        self.main = os.path.join(self.tmp, "proj")

    # ---- helpers
    def git(self, cwd: str, *args: str, check: bool = True) -> str:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, encoding="utf-8", errors="replace", env=self.env)
        if check and p.returncode:
            raise AssertionError(f"git {args} 실패: {p.stderr}")
        return p.stdout.strip()

    def wt(self, *args: str, cwd: str | None = None, expect: int | None = 0) -> subprocess.CompletedProcess:
        p = subprocess.run([sys.executable, WT_PY, *args], cwd=cwd or self.main, capture_output=True,
                           encoding="utf-8", errors="replace", env=self.env, timeout=300)
        if expect is not None:
            self.assertEqual(p.returncode, expect, f"wt {args} rc={p.returncode}\n--stdout--\n{p.stdout}\n--stderr--\n{p.stderr}")
        return p

    def wtj(self, *args: str, cwd: str | None = None, expect: int | None = 0) -> dict:
        p = self.wt(*args, "--json", cwd=cwd, expect=expect)
        return json.loads(p.stdout)

    def path(self, slug: str) -> str:
        return os.path.join(self.tmp, "proj.wt", slug)

    def commit(self, cwd: str, rel: str, text: str, msg: str | None = None) -> str:
        _write(os.path.join(cwd, rel), text)
        self.git(cwd, "add", rel)
        self.git(cwd, "commit", "-q", "-m", msg or f"edit {rel}")
        return self.git(cwd, "rev-parse", "HEAD")

    def seed_push(self, rel: str, text: str) -> str:
        self.git(self.seed, "pull", "-q", "--no-rebase", "origin", "main")
        sha = self.commit(self.seed, rel, text, f"seed {rel}")
        self.git(self.seed, "push", "-q", "origin", "main")
        return sha

    def make_repo(self, *, remote: bool = True) -> None:
        files = {
            ".gitignore": ".env\n.env.*\n!.env.example\nnode_modules/\nbuild/\nCLAUDE.local.md\n.claude/settings.local.json\nsecrets/\n",
            "app.txt": "a\nb\nc\n", ".env.example": "KEY=example\n", "client/app.js": "console.log(1)\n", "README.md": "# proj\n",
        }
        target = self.seed if remote else self.main
        self.git(self.tmp, "init", "-q", "-b", "main", target)
        for rel, text in files.items():
            _write(os.path.join(target, rel), text)
        self.git(target, "add", ".")
        self.git(target, "commit", "-q", "-m", "init")
        if remote:
            self.git(self.tmp, "init", "-q", "--bare", "-b", "main", self.origin)
            self.git(self.seed, "remote", "add", "origin", self.origin)
            self.git(self.seed, "push", "-q", "-u", "origin", "main")
            self.git(self.tmp, "clone", "-q", self.origin, self.main)

    def make_main_busy(self) -> None:
        m = self.main
        _write(os.path.join(m, "app.txt"), "a\nb-main-dirty\nc\n")          # 수정 (unstaged)
        _write(os.path.join(m, "README.md"), "# proj staged\n")              # 수정 (staged)
        self.git(m, "add", "README.md")
        _write(os.path.join(m, "notes.txt"), "untracked\n")                  # untracked
        _write(os.path.join(m, ".env.example"), "KEY=dirty-main\n")         # 추적 파일 수정
        _write(os.path.join(m, ".env"), "SECRET=main\n")                     # ignored → 복사 대상
        _write(os.path.join(m, "client", ".env"), "CLIENT=1\n")
        _write(os.path.join(m, "CLAUDE.local.md"), "local rules\n")
        _write(os.path.join(m, ".claude", "settings.local.json"), "{}\n")
        _write(os.path.join(m, "node_modules", "pkg", ".env"), "NM=1\n")    # 의존성 폴더 → 복사 안 함
        _write(os.path.join(m, ".env.big"), "x" * (1024 * 1024 + 10))       # 1MB 초과 → 복사 안 함

    def snapshot(self, path: str) -> dict:
        files = {}
        for root, dirs, names in os.walk(path):
            dirs[:] = [d for d in dirs if d != ".git"]
            for n in names:
                full = os.path.join(root, n)
                files[os.path.relpath(full, path)] = _sha(full)
        return {
            "head": self.git(path, "rev-parse", "HEAD"),
            "branch": self.git(path, "symbolic-ref", "-q", "HEAD", check=False),
            "index": self.git(path, "ls-files", "-s"),
            "status": self.git(path, "status", "--porcelain", "--untracked-files=all"),
            "stash": self.git(path, "stash", "list"),
            "files": files,
        }

    def rows(self, data: dict) -> dict:
        return {r["slug"] or r["path"]: r for r in data["worktrees"]}


class NewTests(RepoCase):
    def test_new_creates_worktree_copies_ignored_env_and_leaves_main_untouched(self):
        self.make_repo()
        self.make_main_busy()
        before = self.snapshot(self.main)
        p = self.wt("new", "login-fix")
        path = self.path("login-fix")
        last = [ln for ln in p.stdout.splitlines() if ln.strip()][-1]
        self.assertTrue(last.startswith("WORKTREE: "), last)
        self.assertTrue(_same(last[len("WORKTREE: "):], path))
        self.assertTrue(os.path.isdir(path))
        self.assertIn("worktree", self.git(self.main, "worktree", "list", "--porcelain"))
        self.assertEqual(self.git(path, "rev-parse", "--abbrev-ref", "HEAD"), "wt/login-fix")
        self.assertEqual(self.git(path, "rev-parse", "HEAD"), self.git(self.main, "rev-parse", "origin/main"))
        # ignored 로컬 설정은 복사, 추적 파일은 커밋된 내용, 나머지는 복사 안 함
        self.assertEqual(_read(os.path.join(path, ".env")), "SECRET=main\n")
        self.assertEqual(_read(os.path.join(path, "client", ".env")), "CLIENT=1\n")
        self.assertTrue(os.path.isfile(os.path.join(path, "CLAUDE.local.md")))
        self.assertTrue(os.path.isfile(os.path.join(path, ".claude", "settings.local.json")))
        self.assertFalse(os.path.exists(os.path.join(path, "node_modules")))
        self.assertFalse(os.path.exists(os.path.join(path, ".env.big")))
        self.assertFalse(os.path.exists(os.path.join(path, "notes.txt")))
        self.assertEqual(_read(os.path.join(path, ".env.example")), "KEY=example\n")
        self.assertEqual(_read(os.path.join(path, "app.txt")), "a\nb\nc\n")
        self.assertEqual(self.git(path, "status", "--porcelain", "--untracked-files=all"), "")
        # 상태 파일 = .git/worktrees/<id>/make-worktree.json
        sp = self.git(path, "rev-parse", "--path-format=absolute", "--git-path", "make-worktree.json")
        self.assertIn(os.path.join(".git", "worktrees"), os.path.normpath(sp))
        with open(sp, encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual((state["slug"], state["branch"], state["port_offset"]), ("login-fix", "wt/login-fix", 1))
        copied = {c["path"]: c["sha256"] for c in state["copied"]}
        self.assertEqual(copied[".env"], hashlib.sha256(b"SECRET=main\n").hexdigest())
        self.assertEqual(set(copied), {".env", "client/.env", "CLAUDE.local.md", ".claude/settings.local.json"})
        self.assertEqual(self.snapshot(self.main), before)

    def test_new_is_idempotent_and_rejects_bad_input(self):
        self.make_repo()
        self.wt("new", "login-fix")
        p = self.wt("new", "login-fix")
        self.assertIn("이미 있다", p.stdout)
        self.assertEqual(len(self.git(self.main, "worktree", "list", "--porcelain").split("\n\n")), 2)
        self.wt("new", "Bad_Slug", expect=2)
        self.wt("new", "x" * 31, expect=2)
        self.wt("new", "other", "--branch", "wt/login-fix", expect=2)
        self.wt("new", "other2", "--branch", "bad..name", expect=2)
        self.assertFalse(os.path.exists(self.path("other")))

    def test_worktreeinclude_and_port_offsets(self):
        self.make_repo()
        _write(os.path.join(self.main, ".worktreeinclude"), "# 패턴\nsecrets/*.json\n")
        _write(os.path.join(self.main, "secrets", "a.json"), "{\"k\": 1}\n")
        _write(os.path.join(self.main, "secrets", "b.txt"), "nope\n")
        _write(os.path.join(self.main, ".env"), "SECRET=1\n")
        d1 = self.wtj("new", "w-one")
        self.assertEqual(d1["copied"], ["secrets/a.json"])  # .worktreeinclude 가 기본 목록을 대신한다
        self.assertEqual(d1["include_source"], ".worktreeinclude")
        self.assertEqual(d1["port_offset"], 1)
        self.assertEqual(d1["worktree"].replace("\\", "/").split("/")[-2:], ["proj.wt", "w-one"])
        d2 = self.wtj("new", "w-two", cwd=self.path("w-one"))  # linked worktree 안에서 불러도 메인 옆에 만든다
        self.assertTrue(_same(d2["worktree"], self.path("w-two")))
        self.assertEqual(d2["copied"], ["secrets/a.json"])
        self.assertEqual(d2["port_offset"], 2)
        self.assertNotIn(8000, d2["ports"].values())
        self.wt("remove", "w-one")
        d3 = self.wtj("new", "w-three")
        self.assertEqual(d3["port_offset"], 1)  # 비어 있는 가장 작은 오프셋


    def test_from_head_starts_at_main_commit(self):
        self.make_repo()
        local = self.commit(self.main, "local.txt", "unpushed\n")
        _write(os.path.join(self.main, "wip.txt"), "uncommitted\n")
        d = self.wtj("new", "fh", "--from-head")
        path = self.path("fh")
        self.assertEqual(self.git(path, "rev-parse", "HEAD"), local)
        self.assertTrue(os.path.isfile(os.path.join(path, "local.txt")))
        self.assertFalse(os.path.exists(os.path.join(path, "wip.txt")))  # 커밋된 상태만
        self.assertEqual(d["base_ref"], "origin/main")


class StatusTests(RepoCase):
    def test_status_flags_and_recommendation(self):
        self.make_repo()
        self.make_main_busy()
        self.wt("new", "s-unpushed")
        self.commit(self.path("s-unpushed"), "feature.txt", "f\n")
        self.wt("new", "s-dirty")
        _write(os.path.join(self.path("s-dirty"), "scratch.txt"), "wip\n")
        self.seed_push("seed.txt", "s\n")
        self.wt("new", "s-merged")
        self.commit(self.path("s-merged"), "merged.txt", "m\n")
        self.wt("finish", "s-merged", "--mode", "push")
        self.wt("new", "s-gone")
        _rmtree(self.path("s-gone"))
        self.wt("new", "s-fresh")
        self.git(self.main, "worktree", "add", "-q", "--detach", os.path.join(self.tmp, "manual"))
        data = self.wtj("status", "--fetch")
        rows = self.rows(data)
        self.assertEqual(set(rows), {"s-unpushed", "s-dirty", "s-merged", "s-gone", "s-fresh"})
        self.assertIn("UNPUSHED 1", rows["s-unpushed"]["flags"])
        self.assertTrue(any(f.startswith("BEHIND ") for f in rows["s-unpushed"]["flags"]), rows["s-unpushed"]["flags"])
        self.assertIn("DIRTY", rows["s-dirty"]["flags"])
        self.assertIn("MERGED→remove", rows["s-merged"]["flags"])
        self.assertIn("PRUNABLE", rows["s-gone"]["flags"])
        self.assertNotIn("MERGED→remove", rows["s-fresh"]["flags"])  # 커밋 없는 새 worktree 는 merged 가 아니다
        self.assertEqual(data["unmanaged"], 1)
        self.assertEqual(data["recommend"]["mode"], "push")  # origin 이 GitHub 이 아닌 로컬 bare
        self.assertGreater(data["signals"]["main_dirty"], 0)
        all_rows = self.wtj("status", "--all")["worktrees"]
        self.assertTrue(any(r["main"] for r in all_rows))
        self.assertTrue(any(_same(r["path"], os.path.join(self.tmp, "manual")) for r in all_rows))


class SyncTests(RepoCase):
    def test_sync_merges_base_and_reports_conflicts_with_exit_3(self):
        self.make_repo()
        self.make_main_busy()
        before = self.snapshot(self.main)
        self.wt("new", "y-one")
        y1 = self.path("y-one")
        self.commit(y1, "y.txt", "y\n")
        self.seed_push("other.txt", "o\n")
        d = self.wtj("sync", "y-one")
        self.assertTrue(d["changed"])
        self.assertEqual(_read(os.path.join(y1, "other.txt")), "o\n")
        self.assertEqual(len(self.git(y1, "rev-list", "--parents", "-n", "1", "HEAD").split()), 3)
        self.assertFalse(self.wtj("sync", "y-one")["changed"])  # 다시 실행해도 안전
        # 충돌
        self.wt("new", "y-two")
        y2 = self.path("y-two")
        self.commit(y2, "app.txt", "a\nb-wt\nc\n")
        self.seed_push("app.txt", "a\nb-origin\nc\n")
        d = self.wtj("sync", "y-two", expect=3)
        self.assertEqual(d["conflicts"], ["app.txt"])
        self.assertTrue(os.path.exists(self.git(y2, "rev-parse", "--path-format=absolute", "--git-path", "MERGE_HEAD")))
        p = self.wt("sync", "y-two", expect=3)
        self.assertIn("app.txt", p.stderr)
        self.assertEqual(self.snapshot(self.main), before)

    def test_sync_rebase_only_for_unpushed_branch(self):
        self.make_repo()
        self.wt("new", "rb")
        rb = self.path("rb")
        self.commit(rb, "rb.txt", "r\n")
        self.seed_push("other.txt", "o\n")
        self.wt("sync", "rb", "--rebase")
        self.assertEqual(self.git(rb, "rev-parse", "HEAD~1"), self.git(rb, "rev-parse", "origin/main"))  # 선형
        self.git(rb, "push", "-q", "-u", "origin", "wt/rb")
        self.seed_push("more.txt", "m\n")
        self.wt("sync", "rb", "--rebase", expect=2)  # push 한 브랜치는 rebase 하지 않는다
        self.wt("sync", "rb")

    def test_sync_refuses_dirty_worktree(self):
        self.make_repo()
        self.wt("new", "z-one")
        _write(os.path.join(self.path("z-one"), "wip.txt"), "x\n")
        self.seed_push("other.txt", "o\n")
        p = self.wt("sync", "z-one", expect=2)
        self.assertIn("wip.txt", p.stderr)


class FinishTests(RepoCase):
    def test_finish_push_creates_no_ff_merge_on_origin(self):
        self.make_repo()
        self.make_main_busy()
        before = self.snapshot(self.main)
        self.wt("new", "f-one")
        path = self.path("f-one")
        tip = self.commit(path, "f.txt", "f\n")
        old = self.git(self.origin, "rev-parse", "main")
        plan = self.wtj("finish", "f-one")  # --mode 없으면 점검·추천만
        self.assertTrue(plan["ready"])
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), old)
        self.wt("finish", "f-one", "--mode", "push")
        new = self.git(self.origin, "rev-parse", "main")
        self.assertEqual(self.git(self.origin, "rev-list", "--parents", "-n", "1", "main").split(), [new, old, tip])
        self.assertEqual(self.git(path, "rev-parse", "HEAD"), new)
        self.assertEqual(self.git(path, "symbolic-ref", "-q", "HEAD", check=False), "")  # detached
        p = self.wt("finish", "f-one", "--mode", "push")
        self.assertIn("이미", p.stdout)
        self.assertEqual(self.snapshot(self.main), before)
        self.wt("remove", "f-one", "--delete-branch")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.git(self.main, "branch", "--list", "wt/f-one"), "")
        self.assertEqual(self.snapshot(self.main), before)

    def test_finish_push_retries_once_after_rejection(self):
        self.make_repo()
        self.wt("new", "race")
        tip = self.commit(self.path("race"), "mine.txt", "m\n")
        marker = os.path.join(self.tmp, "hook-ran").replace("\\", "/")
        seed = self.seed.replace("\\", "/")
        hook = os.path.join(self.main, ".git", "hooks", "pre-push")
        _write(hook, "#!/bin/sh\n"
                     f'if [ ! -f "{marker}" ]; then\n'
                     f'  : > "{marker}"\n'
                     "  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_COMMON_DIR\n"
                     f'  cd "{seed}" && echo race > race.txt && git add race.txt && git commit -q -m race && git push -q origin main\n'
                     "fi\nexit 0\n")
        os.chmod(hook, 0o755)
        d = self.wtj("finish", "race", "--mode", "push")
        self.assertTrue(d["retried"], d)
        race = self.git(self.seed, "rev-parse", "HEAD")
        new = self.git(self.origin, "rev-parse", "main")
        self.assertEqual(self.git(self.origin, "rev-list", "--parents", "-n", "1", "main").split(), [new, race, tip])

    def test_finish_local_keeps_busy_main_untouched(self):
        self.make_repo(remote=False)
        self.make_main_busy()
        before = self.snapshot(self.main)
        self.wt("new", "l-one")
        self.commit(self.path("l-one"), "l.txt", "l\n")
        old = self.git(self.main, "rev-parse", "refs/heads/main")
        p = self.wt("finish", "l-one", "--mode", "local")
        self.assertIn('merge --no-ff --no-edit "wt/l-one"', p.stdout)
        self.assertEqual(self.git(self.main, "rev-parse", "refs/heads/main"), old)
        self.assertNotEqual(self.git(self.main, "branch", "--list", "wt/l-one"), "")
        self.assertEqual(self.snapshot(self.main), before)
        rows = self.rows(self.wtj("status"))
        self.assertIn("LOCAL-PENDING", rows["l-one"]["flags"])
        self.wt("remove", "l-one", expect=2)  # 아직 어디에도 합쳐지지 않았다

    def test_finish_local_moves_ref_when_base_not_checked_out(self):
        self.make_repo(remote=False)
        self.git(self.main, "switch", "-q", "-c", "dev")
        self.make_main_busy()
        before = self.snapshot(self.main)
        self.wt("new", "l-two", "--base", "main")
        tip = self.commit(self.path("l-two"), "l.txt", "l\n")
        old = self.git(self.main, "rev-parse", "refs/heads/main")
        self.wt("finish", "l-two", "--mode", "local")
        new = self.git(self.main, "rev-parse", "refs/heads/main")
        self.assertEqual(self.git(self.main, "rev-list", "--parents", "-n", "1", new).split(), [new, old, tip])
        self.assertEqual(self.snapshot(self.main), before)
        self.wt("remove", "l-two", "--delete-branch")
        self.assertEqual(self.git(self.main, "branch", "--list", "wt/l-two"), "")

    def test_finish_refuses_when_base_moved_until_sync(self):
        self.make_repo()
        self.wt("new", "behind")
        self.commit(self.path("behind"), "b.txt", "b\n")
        self.seed_push("other.txt", "o\n")
        p = self.wt("finish", "behind", "--mode", "push", expect=2)
        self.assertIn("sync", p.stderr)
        self.wt("sync", "behind")
        self.wt("finish", "behind", "--mode", "push")

    def test_finish_push_declined_by_protection_is_not_retried(self):
        self.make_repo()
        self.wt("new", "prot")
        path = self.path("prot")
        self.commit(path, "p.txt", "p\n")
        _write(os.path.join(self.origin, "hooks", "pre-receive"),
               "#!/bin/sh\necho 'remote: error: GH006: Protected branch update failed for refs/heads/main.' >&2\nexit 1\n")
        old = self.git(self.origin, "rev-parse", "main")
        p = self.wt("finish", "prot", "--mode", "push", expect=2)
        self.assertIn("pr 모드", p.stderr)
        self.assertNotIn("다시 한다", p.stdout)  # 보호 거부는 재시도하지 않는다
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), old)
        self.assertEqual(self.git(path, "rev-parse", "--abbrev-ref", "HEAD"), "wt/prot")  # 브랜치로 되돌아온다

    def test_pr_mode_dry_run_builds_commands_without_pushing(self):
        self.make_repo()
        url = "https://github.com/example/demo.git"
        self.git(self.main, "config", "remote.origin.url", url)
        self.git(self.main, "config", f"url.{self.origin.replace(chr(92), '/')}.insteadOf", url)  # 실제 전송은 로컬 bare 로
        self.wt("new", "p-one")
        self.commit(self.path("p-one"), "p.txt", "p\n")
        p = self.wt("finish", "p-one", "--mode", "pr", "--dry-run", "--title", "Fix login")
        self.assertIn('push -u origin "wt/p-one"', p.stdout)
        self.assertIn('gh pr create -R example/demo --base main --head "wt/p-one" --title "Fix login" --body ""', p.stdout)
        self.wt("finish", "p-one", "--mode", "pr", expect=2)  # gh 를 쓸 수 없으면 거부, 아무것도 push 하지 않는다
        self.assertEqual(self.git(self.origin, "branch", "--list", "wt/p-one"), "")


class RemoveCleanTests(RepoCase):
    def test_remove_refuses_dirty_then_backs_up_changed_env(self):
        self.make_repo()
        self.make_main_busy()
        before = self.snapshot(self.main)
        self.wt("new", "r-one")
        path = self.path("r-one")
        _write(os.path.join(path, "scratch.txt"), "wip\n")
        p = self.wt("remove", "r-one", expect=2)
        self.assertIn("scratch.txt", p.stderr)
        self.assertTrue(os.path.isdir(path))
        os.remove(os.path.join(path, "scratch.txt"))
        _write(os.path.join(path, ".env"), "SECRET=changed-in-worktree\n")
        _write(os.path.join(path, ".env.local"), "NEW=1\n")
        d = self.wtj("remove", "r-one", "--delete-branch")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(sorted(d["backed_up"]), [".env", ".env.local"])
        backups = glob.glob(os.path.join(self.tmp, "proj.wt", ".backup", "r-one-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(_read(os.path.join(backups[0], ".env")), "SECRET=changed-in-worktree\n")
        self.assertFalse(os.path.exists(os.path.join(backups[0], "CLAUDE.local.md")))  # 바뀌지 않은 복사본은 백업 안 함
        self.assertEqual(self.git(self.main, "branch", "--list", "wt/r-one"), "")
        self.assertEqual(self.git(self.main, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(self.snapshot(self.main), before)

    def test_remove_refuses_unpushed_commits_and_own_cwd(self):
        self.make_repo()
        self.wt("new", "r-two")
        self.commit(self.path("r-two"), "r.txt", "r\n")
        p = self.wt("remove", "r-two", expect=2)
        self.assertIn("--force", p.stderr)
        self.wt("remove", "r-two", "--force")
        self.assertFalse(os.path.exists(self.path("r-two")))
        self.assertNotEqual(self.git(self.main, "branch", "--list", "wt/r-two"), "")  # 커밋은 브랜치에 남는다
        self.wt("new", "r-three")
        p = self.wt("remove", "r-three", cwd=self.path("r-three"), expect=2)
        self.assertIn("cwd", p.stderr)
        self.wt("remove", "r-three")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "proj.wt")))  # 비면 <repo>.wt 도 지운다

    def test_clean_is_dry_run_by_default(self):
        self.make_repo()
        self.wt("new", "c-one")
        self.commit(self.path("c-one"), "c.txt", "c\n")
        self.wt("finish", "c-one", "--mode", "push")
        self.wt("new", "c-two")
        p = self.wt("clean")
        self.assertIn("dry-run", p.stdout)
        self.assertIn("c-one", p.stdout)
        self.assertNotIn("c-two", p.stdout)
        self.assertTrue(os.path.isdir(self.path("c-one")))
        self.assertNotEqual(self.git(self.main, "branch", "--list", "wt/c-one"), "")
        self.wt("clean", "--yes")
        self.assertFalse(os.path.exists(self.path("c-one")))
        self.assertTrue(os.path.isdir(self.path("c-two")))
        self.assertEqual(self.git(self.main, "branch", "--list", "wt/c-one"), "")

    def test_remove_leaves_tracked_symlinks_to_git(self):
        self.make_repo()
        self.git(self.seed, "config", "core.symlinks", "true")
        try:
            os.symlink("app.txt", os.path.join(self.seed, "link.txt"))
        except (OSError, NotImplementedError):
            self.skipTest("symlink 을 만들 권한이 없다")
        self.git(self.seed, "add", "link.txt")
        self.git(self.seed, "commit", "-q", "-m", "tracked symlink")
        self.git(self.seed, "push", "-q", "origin", "main")
        self.git(self.main, "config", "core.symlinks", "true")
        self.wt("new", "sl")
        path = self.path("sl")
        self.assertTrue(os.path.islink(os.path.join(path, "link.txt")))
        d = self.wtj("remove", "sl")
        self.assertEqual(d["links_unlinked"], 0)  # 추적 symlink 를 먼저 지우면 dirty 가 되어 remove 가 거부된다
        self.assertFalse(os.path.lexists(path))

    @unittest.skipUnless(os.name == "nt", "Windows junction 전용")
    def test_remove_unlinks_junction_and_keeps_target(self):
        self.make_repo()
        self.wt("new", "j-one")
        path = self.path("j-one")
        target = os.path.join(self.tmp, "shared-deps")
        _write(os.path.join(target, "keep.txt"), "keep\n")
        subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(path, "node_modules"), target],
                       check=True, capture_output=True)
        self.assertTrue(wt.is_link(os.path.join(path, "node_modules")))
        self.assertEqual(self.git(path, "status", "--porcelain", "--untracked-files=all"), "")  # ignored
        d = self.wtj("remove", "j-one")
        self.assertEqual(d["links_unlinked"], 1)
        self.assertFalse(os.path.lexists(path))  # 좀비 폴더가 남지 않는다
        self.assertEqual(_read(os.path.join(target, "keep.txt")), "keep\n")  # 대상은 그대로


class PureTests(unittest.TestCase):
    def test_include_matcher(self):
        m = wt.IncludeMatcher(list(wt.DEFAULT_INCLUDE))
        for rel in (".env", ".env.local", "client/.env", "a/b/.env.test", "CLAUDE.local.md", ".claude/settings.local.json"):
            self.assertTrue(m.match(rel), rel)
        for rel in ("env", "x.env", ".claude/settings.json", "client/app.js", "sub/.claude/settings.local.json"):
            self.assertFalse(m.match(rel), rel)
        m = wt.IncludeMatcher(["client/e2e/.auth/", "/root.json", "*.key", "!keep.key", "docs/**/*.md"])
        self.assertTrue(m.match("client/e2e/.auth/state.json"))
        self.assertTrue(m.match("root.json"))
        self.assertFalse(m.match("sub/root.json"))
        self.assertTrue(m.match("deep/x.key"))
        self.assertFalse(m.match("keep.key"))
        self.assertTrue(m.match("docs/a/b/c.md"))
        self.assertTrue(m.match("docs/c.md"))

    def test_build_pr_create_cmd(self):
        self.assertEqual(wt.build_pr_create_cmd("o/r", "main", "wt/x"),
                         ["gh", "pr", "create", "-R", "o/r", "--base", "main", "--head", "wt/x", "--fill"])
        self.assertEqual(wt.build_pr_create_cmd("o/r", "main", "wt/x", title="T")[-4:], ["--title", "T", "--body", ""])
        self.assertEqual(wt.build_pr_create_cmd("o/r", "main", "wt/x", body_file="b.md", default_title="subj")[-4:],
                         ["--title", "subj", "--body-file", "b.md"])

    def test_parse_github(self):
        self.assertEqual(wt.parse_github("https://github.com/Tak002/skills.git"), ("Tak002", "skills"))
        self.assertEqual(wt.parse_github("git@github.com:o/r.git"), ("o", "r"))
        self.assertEqual(wt.parse_github("ssh://git@github.com/o/r"), ("o", "r"))
        self.assertIsNone(wt.parse_github("https://dev.azure.com/org/p/_git/r"))
        self.assertIsNone(wt.parse_github("C:/tmp/origin.git"))

    def test_recommend_mode(self):
        base = {"origin": "https://github.com/me/r.git", "github": "me/r", "owner": "me", "gh_user": "me",
                "protected": False, "pr_docs": [], "pr_docs_negative": [], "custom_merge_docs": []}
        self.assertEqual(wt.recommend_mode(base)[0], "push")
        self.assertEqual(wt.recommend_mode({**base, "protected": True})[0], "pr")
        self.assertEqual(wt.recommend_mode({**base, "gh_user": "other"})[0], "pr")
        self.assertEqual(wt.recommend_mode({**base, "pr_docs": ["AGENTS.md:3: PR 로 올린다"]})[0], "pr")
        self.assertEqual(wt.recommend_mode({**base, "custom_merge_docs": ["CLAUDE.md:9: relay-hub finish-task"]})[0], "delegate")
        self.assertEqual(wt.recommend_mode({**base, "origin": None, "github": None})[0], "local")
        self.assertEqual(wt.recommend_mode({**base, "github": None, "origin": "https://gitlab.com/x/y"})[0], "push")
        self.assertEqual(wt.recommend_mode({**base, "github": None, "origin": "https://dev.azure.com/o/p/_git/r",
                                            "pr_docs": ["CONTRIBUTING.md:4: PR 필수"]})[0], "delegate")

    def test_detect_installs(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "client", "pnpm-lock.yaml"), "lockfileVersion: '9.0'\n")
            _write(os.path.join(d, "client", "package-lock.json"), "{}\n")  # pnpm 이 우선
            _write(os.path.join(d, "api", "uv.lock"), "version = 1\n")
            _write(os.path.join(d, "tools", "requirements-dev.txt"), "pytest\n")
            _write(os.path.join(d, "server", "build.gradle"), "\n")
            _write(os.path.join(d, "node_modules", "x", "package-lock.json"), "{}\n")  # 의존성 폴더는 보지 않는다
            items = {(i["dir"], i["file"]): i for i in wt.detect_installs(d)}
            self.assertEqual(set(items), {("client", "pnpm-lock.yaml"), ("api", "uv.lock"),
                                          ("tools", "requirements-dev.txt"), ("server", "gradle/maven")})
            self.assertEqual(items[("client", "pnpm-lock.yaml")]["cmd"][:3], ["corepack", "pnpm", "install"])
            self.assertTrue(items[("api", "uv.lock")]["run"])
            self.assertFalse(items[("tools", "requirements-dev.txt")]["run"])  # venv 는 힌트만
            self.assertFalse(items[("server", "gradle/maven")]["run"])

    def test_suggest_ports_avoid_reserved(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(wt.suggest_ports(d, 1), {"vite": 5183, "web": 3010, "api": 8010, "spring": 8090})
            ports = wt.suggest_ports(d, 500)  # 3000 + 5000 = 8000 → 피한다
            self.assertNotIn(8000, ports.values())
            self.assertNotIn(8001, ports.values())


if __name__ == "__main__":
    unittest.main()
