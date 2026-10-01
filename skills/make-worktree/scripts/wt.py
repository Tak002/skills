#!/usr/bin/env python
"""make-worktree — git worktree 로 작업별 일회용 폴더를 만들고(new) 보고(status) 동기화하고(sync)
합치고(finish) 지운다(remove, clean).

  python wt.py new <slug> [--branch B] [--base REF] [--from-head] [--no-fetch] [--no-copy] [--install]
  python wt.py status [--all] [--fetch]
  python wt.py sync [slug|경로] [--rebase] [--no-fetch] [--base B]
  python wt.py finish [slug|경로] [--mode pr|push|local] [--title T] [--body-file F] [--dry-run] [--no-fetch]
  python wt.py remove <slug|경로> [--delete-branch] [--force]
  python wt.py clean [--yes]
  공통 옵션: --repo PATH (기본: 현재 폴더), --json

폴더 규칙: <메인 worktree 의 부모>/<repo>.wt/<slug>/   (메인 = git worktree list 의 첫 항목)
상태 파일: git -C <worktree> rev-parse --git-path make-worktree.json  (= .git/worktrees/<id>/make-worktree.json)
종료 코드: 0 성공 · 1 오류 · 2 거부(전제 조건·인자) · 3 충돌 · 4 정리 미완(폴더가 남음)

메인 체크아웃의 작업 트리·index·checkout 된 브랜치는 바꾸지 않는다. 표준 라이브러리만 쓴다 (Python 3.10+).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass

TOOL = "make-worktree"
STATE_NAME = "make-worktree.json"
LOCK_NAME = "make-worktree.lock"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SLUG_MAX = 30
DEFAULT_INCLUDE = (".env", ".env.*", "**/.env", "**/.env.*", "CLAUDE.local.md", ".claude/settings.local.json")
SKIP_DIRS = frozenset({
    "node_modules", ".venv", "venv", "build", "dist", "target", "out", ".gradle", "__pycache__",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache", ".parcel-cache", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", "coverage", ".pnpm-store", "bower_components",
})
MAX_COPY_BYTES = 1024 * 1024
PORT_STRIDE = 10
AVOID_PORTS = frozenset({8000, 8001})
PORT_BASES = {"vite": 5173, "web": 3000, "api": 8000, "spring": 8080}
JS_LOCKS = (
    ("pnpm-lock.yaml", ["corepack", "pnpm", "install", "--frozen-lockfile", "--prefer-offline"]),
    ("yarn.lock", ["yarn", "install", "--frozen-lockfile"]),
    ("package-lock.json", ["npm", "ci"]),
)
IS_WINDOWS = os.name == "nt"
SELF = os.path.abspath(__file__)
NO_GH_ENV = "MAKE_WORKTREE_NO_GH"  # 1 이면 gh 를 부르지 않는다 (테스트·오프라인)

OK, ERROR, REFUSED, CONFLICT, LEFTOVER = 0, 1, 2, 3, 4


# ---------------------------------------------------------------- 오류·출력

class WtError(Exception):
    """사용자에게 보여 줄 실패. code 는 종료 코드, details 는 근거 줄."""

    def __init__(self, message: str, code: int = ERROR, details: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.details = list(details or [])


def refuse(message: str, details: list[str] | None = None) -> None:
    raise WtError(message, REFUSED, details)


class Out:
    """사람용 출력은 stdout. --json 이면 진행 메시지는 stderr, stdout 에는 마지막 JSON 하나만."""

    def __init__(self, json_mode: bool):
        self.json_mode = json_mode
        self.data: dict = {}
        self.warnings: list[str] = []

    def say(self, text: str = "") -> None:
        print(text, file=sys.stderr if self.json_mode else sys.stdout, flush=True)

    def warn(self, text: str) -> None:
        self.warnings.append(text)
        self.say(f"경고: {text}")


_SPECIAL = re.compile(r"[\s#&;|<>()'\"$`^%!*?,{}\[\]]")


def q(s: object) -> str:
    """사람이 복사해 쓸 명령 표시용 인용."""
    s = str(s)
    if s and not _SPECIAL.search(s):
        return s
    return '"' + s.replace('"', '\\"') + '"'


def qb(branch: str) -> str:
    """브랜치 이름은 항상 인용한다 (# 가 셸에서 주석으로 잘린다)."""
    return '"' + branch.replace('"', '\\"') + '"'


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def ago(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        then = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        sec = max(0, int((_dt.datetime.now(_dt.timezone.utc) - then).total_seconds()))
    except (ValueError, TypeError):
        return iso
    if sec < 60:
        return "방금"
    if sec < 3600:
        return f"{sec // 60}분 전"
    if sec < 86400:
        return f"{sec // 3600}시간 전"
    return f"{sec // 86400}일 전"


# ---------------------------------------------------------------- 프로세스·git

def _env() -> dict:
    env = dict(os.environ)
    # 프롬프트로 멈추지 않고, git status 가 index 를 다시 쓰지 않게(바쁜 메인과 index.lock 경합 방지)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_MERGE_AUTOEDIT": "no", "LANGUAGE": "C"})
    return env


def run(argv: list[str], *, cwd: str | None = None, timeout: int | None = 120,
        input_text: str | None = None) -> subprocess.CompletedProcess:
    kwargs: dict = {"cwd": cwd, "capture_output": True, "encoding": "utf-8", "errors": "replace",
                    "env": _env(), "timeout": timeout}
    if input_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input_text
    try:
        return subprocess.run(argv, **kwargs)
    except FileNotFoundError:
        raise WtError(f"실행 파일을 찾지 못했다: {argv[0]}") from None
    except subprocess.TimeoutExpired:
        raise WtError(f"{timeout}초 안에 끝나지 않았다: {' '.join(map(str, argv[:6]))}") from None


def _tail(p: subprocess.CompletedProcess, n: int = 8) -> list[str]:
    text = ((p.stderr or "") + "\n" + (p.stdout or "")).strip()
    return [ln for ln in text.splitlines() if ln.strip()][-n:]


def git(cwd: str, *args: str, check: bool = True, timeout: int | None = 120,
        input_text: str | None = None) -> subprocess.CompletedProcess:
    p = run(["git", "-C", cwd, "-c", "core.quotepath=false", *args], timeout=timeout, input_text=input_text)
    if check and p.returncode != 0:
        raise WtError(f"git {' '.join(args[:3])} 실패 (rc={p.returncode})", ERROR, _tail(p))
    return p


def gout(cwd: str, *args: str, **kw) -> str:
    return git(cwd, *args, **kw).stdout.strip()


def gok(cwd: str, *args: str) -> bool:
    return git(cwd, *args, check=False).returncode == 0


def ref_exists(cwd: str, ref: str) -> bool:
    return gok(cwd, "show-ref", "--verify", "--quiet", ref)


def rev(cwd: str, ref: str | None) -> str | None:
    if not ref:
        return None
    p = git(cwd, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return p.stdout.strip() or None if p.returncode == 0 else None


def is_ancestor(cwd: str, a: str, b: str) -> bool:
    return gok(cwd, "merge-base", "--is-ancestor", a, b)


def count(cwd: str, *rev_args: str, strict: bool = False) -> int:
    """rev-list --count. strict 면 실패를 0 으로 삼키지 않는다 (안전 판정에 쓰는 값)."""
    p = git(cwd, "rev-list", "--count", *rev_args, check=strict)
    try:
        return int(p.stdout.strip())
    except ValueError:
        if strict:
            raise WtError("git rev-list --count 결과를 읽지 못했다", ERROR, _tail(p))
        return 0


def left_right(cwd: str, base_ref: str, head: str = "HEAD") -> tuple[int, int]:
    """(behind, ahead) — base 에만 있는 커밋 수, head 에만 있는 커밋 수."""
    p = git(cwd, "rev-list", "--left-right", "--count", f"{base_ref}...{head}", check=False)
    try:
        left, right = p.stdout.split()
        return int(left), int(right)
    except ValueError:
        return 0, 0


def fmt_cmd(argv: list[str], branch: str | None = None) -> str:
    """복사해 쓸 수 있는 명령 문자열. 브랜치 이름은 항상 인용한다."""
    return " ".join(qb(a) if branch and a == branch else q(a) for a in argv)


def step(out: Out, cwd: str, args: list[str], *, check: bool = True, timeout: int | None = 120,
         branch: str | None = None):
    """바꾸는 git 명령은 실행 전에 그대로 보여 준다."""
    out.say(f"  $ git -C {q(cwd)} " + fmt_cmd(args, branch))
    return git(cwd, *args, check=check, timeout=timeout)


def fetch(cwd: str, out: Out, *, write_fetch_head: bool = True) -> bool:
    args = ["fetch", "--prune"]
    if not write_fetch_head:
        args.append("--no-write-fetch-head")  # 메인 쪽 FETCH_HEAD 를 건드리지 않는다 (메인의 git pull 과 경합 방지)
    args.append("origin")
    p = step(out, cwd, args, check=False, timeout=180)
    if p.returncode != 0:
        out.warn("fetch 실패 — 마지막으로 받아 둔 origin 기준으로 계속한다: " + " / ".join(_tail(p, 2)))
        return False
    return True


def dirty_lines(path: str) -> list[str]:
    return [ln for ln in gout(path, "status", "--porcelain", "--untracked-files=all").splitlines() if ln.strip()]


def conflicted(path: str) -> list[str]:
    return [ln for ln in gout(path, "diff", "--name-only", "--diff-filter=U").splitlines() if ln.strip()]


def op_in_progress(path: str) -> str | None:
    names = (("MERGE_HEAD", "merge"), ("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
             ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"))
    args = ["rev-parse", "--path-format=absolute"]
    for n, _ in names:
        args += ["--git-path", n]
    for (_, label), p in zip(names, gout(path, *args).splitlines()):
        if os.path.exists(p):
            return label
    return None


# ---------------------------------------------------------------- 경로

def from_msys(p: str) -> str:
    """Git Bash 형 /w/works/... 를 W:/works/... 로 (Windows 에서만)."""
    if IS_WINDOWS:
        m = re.match(r"^/([A-Za-z])(?=/|$)(.*)$", p)
        if m:
            return f"{m.group(1).upper()}:{m.group(2) or '/'}"
    return p


def display(p: str) -> str:
    return os.path.normpath(os.path.abspath(from_msys(str(p))))


def key(p: str) -> str:
    """비교용 정규화 (/w/... 와 W:/... 불일치, 대소문자, 링크를 흡수)."""
    return os.path.normcase(os.path.realpath(display(p))).rstrip("\\/")


def inside(child: str, parent: str) -> bool:
    c, pk = key(child), key(parent)
    return c == pk or c.startswith(pk + os.sep)


def join_rel(root: str, rel: str) -> str:
    return os.path.join(root, *rel.split("/"))


_LINK_TAGS = {getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C), getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)}


def is_link_stat(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    if IS_WINDOWS and getattr(st, "st_file_attributes", 0) & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        return getattr(st, "st_reparse_tag", 0) in _LINK_TAGS  # junction 또는 symlink (OneDrive 등은 제외)
    return False


def is_link(path: str) -> bool:
    try:
        return is_link_stat(os.lstat(path))
    except OSError:
        return False


def entry_is_link(e: os.DirEntry) -> bool:
    try:
        return is_link_stat(e.stat(follow_symlinks=False))
    except OSError:
        return False


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 저장소 모델

@dataclass
class WT:
    path: str
    head: str | None = None
    branch: str | None = None
    detached: bool = False
    bare: bool = False
    locked: str | None = None  # 잠겼으면 이유 (이유 없으면 "")
    prunable: str | None = None
    is_main: bool = False
    admin: str | None = None
    state: dict | None = None

    @property
    def managed(self) -> bool:
        return bool(self.state and self.state.get("tool") == TOOL)

    @property
    def present(self) -> bool:
        return self.prunable is None and os.path.isdir(self.path)


@dataclass
class Base:
    branch: str | None  # 통합 대상 브랜치 (예: main)
    remote: str | None  # "origin" 또는 None (로컬 브랜치)

    @property
    def ref(self) -> str | None:
        if not self.branch:
            return None
        return f"{self.remote}/{self.branch}" if self.remote else self.branch


@dataclass
class Repo:
    common: str
    worktrees: list
    name: str
    wt_root: str
    git_cwd: str
    remote: str | None

    @property
    def main(self) -> WT:
        return self.worktrees[0]

    @property
    def linked(self) -> list:
        return self.worktrees[1:]

    def find(self, path: str) -> WT | None:
        k = key(path)
        for w in self.worktrees:
            if key(w.path) == k:
                return w
        return None


def parse_worktree_list(text: str) -> list[WT]:
    wts: list[WT] = []
    cur: WT | None = None
    for line in text.splitlines():
        if not line.strip():
            cur = None
            continue
        k, _, v = line.partition(" ")
        if k == "worktree":
            cur = WT(path=display(v))
            wts.append(cur)
        elif cur is None:
            continue
        elif k == "HEAD":
            cur.head = v
        elif k == "branch":
            cur.branch = v[len("refs/heads/"):] if v.startswith("refs/heads/") else v
        elif k == "detached":
            cur.detached = True
        elif k == "bare":
            cur.bare = True
        elif k == "locked":
            cur.locked = v
        elif k == "prunable":
            cur.prunable = v or "prunable"
    if wts:
        wts[0].is_main = True
    return wts


def load_repo(start: str) -> Repo:
    start = display(start)
    if not os.path.isdir(start):
        refuse(f"폴더가 없다: {start}")
    p = git(start, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    if p.returncode != 0:
        refuse(f"git 저장소가 아니다: {start}")
    common = display(p.stdout.strip())
    wts = parse_worktree_list(gout(start, "worktree", "list", "--porcelain"))
    if not wts:
        raise WtError("git worktree list 결과가 비어 있다")
    admins: dict[str, str] = {}
    root = os.path.join(common, "worktrees")
    if os.path.isdir(root):
        for name in os.listdir(root):
            adm = os.path.join(root, name)
            try:
                with open(os.path.join(adm, "gitdir"), encoding="utf-8") as f:
                    gd = from_msys(f.read().strip())
            except OSError:
                continue
            if not os.path.isabs(gd):
                gd = os.path.join(adm, gd)  # worktree.useRelativePaths
            admins[key(os.path.dirname(display(gd)))] = adm
    for w in wts[1:]:
        w.admin = admins.get(key(w.path))
        if w.admin:
            w.state = read_json(os.path.join(w.admin, STATE_NAME))
    main = wts[0]
    main_dir = main.path.rstrip("\\/")
    name = os.path.basename(main_dir)
    if main.bare and name.endswith(".git") and len(name) > 4:
        name = name[:-4]
    git_cwd = main.path if os.path.isdir(main.path) else start
    remote = "origin" if gok(git_cwd, "remote", "get-url", "origin") else None
    return Repo(common=common, worktrees=wts, name=name,
                wt_root=os.path.join(os.path.dirname(main_dir), name + ".wt"), git_cwd=git_cwd, remote=remote)


def state_path_of(wt_path: str) -> str:
    return display(gout(wt_path, "rev-parse", "--path-format=absolute", "--git-path", STATE_NAME))


def save_state(w: WT, state: dict) -> None:
    write_json(os.path.join(w.admin, STATE_NAME) if w.admin else state_path_of(w.path), state)
    w.state = state


def resolve_target(repo: Repo, target: str | None, *, need_present: bool = True) -> WT:
    w = None
    if not target:
        p = git(os.getcwd(), "rev-parse", "--show-toplevel", check=False)
        if p.returncode != 0:
            refuse("대상 worktree 를 알 수 없다 — slug 나 경로를 준다")
        w = repo.find(p.stdout.strip())
    elif SLUG_RE.match(target) and repo.find(os.path.join(repo.wt_root, target)):
        w = repo.find(os.path.join(repo.wt_root, target))
    else:
        w = repo.find(target)
        if w is None and os.path.isdir(display(target)):
            p = git(display(target), "rev-parse", "--show-toplevel", check=False)
            if p.returncode == 0:
                w = repo.find(p.stdout.strip())
    if w is None:
        refuse(f"이 저장소의 worktree 가 아니다: {target or os.getcwd()}",
               [f"목록: python {q(SELF)} status --all"])
    if need_present and not w.present:
        refuse(f"worktree 폴더가 없다 (PRUNABLE): {w.path}", [f"정리: python {q(SELF)} remove {q(w.path)}"])
    return w


# ---------------------------------------------------------------- base

def make_base(repo: Repo, name: str) -> Base:
    cwd = repo.git_cwd
    if repo.remote and name.startswith(repo.remote + "/") and ref_exists(cwd, f"refs/remotes/{name}"):
        return Base(name[len(repo.remote) + 1:], repo.remote)
    if repo.remote and ref_exists(cwd, f"refs/remotes/{repo.remote}/{name}"):
        return Base(name, repo.remote)
    if ref_exists(cwd, f"refs/heads/{name}"):
        return Base(name, None)
    refuse(f"base 브랜치를 찾지 못했다: {name}")
    raise AssertionError  # unreachable


def default_base(repo: Repo, *, soft: bool = False) -> Base:
    cwd = repo.git_cwd
    if repo.remote:
        r = repo.remote
        p = git(cwd, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{r}/HEAD", check=False)
        head = p.stdout.strip()
        if p.returncode == 0 and head.startswith(r + "/"):
            return Base(head[len(r) + 1:], r)
        if not soft:
            p = git(cwd, "ls-remote", "--symref", r, "HEAD", check=False, timeout=60)
            m = re.search(r"^ref: refs/heads/(\S+)\s+HEAD", p.stdout or "", re.M)
            if m and ref_exists(cwd, f"refs/remotes/{r}/{m.group(1)}"):
                return Base(m.group(1), r)
        for b in ("main", "master"):
            if ref_exists(cwd, f"refs/remotes/{r}/{b}"):
                return Base(b, r)
        if soft:
            return Base(None, r)
        refuse("origin 의 기본 브랜치를 모른다 — --base 로 지정한다")
    if repo.main.branch:
        return Base(repo.main.branch, None)
    if soft:
        return Base(None, None)
    refuse("원격이 없고 메인 worktree 가 detached 다 — --base 로 지정한다")
    raise AssertionError  # unreachable


def base_for(repo: Repo, w: WT, override: str | None = None) -> Base:
    if override:
        return make_base(repo, override)
    st = w.state or {}
    if st.get("base_branch"):
        remote = st.get("remote") if st.get("remote") and st.get("remote") == repo.remote else None
        return Base(st["base_branch"], remote)
    return default_base(repo, soft=True)


# ---------------------------------------------------------------- ignored 설정 복사 (.worktreeinclude)

def _translate(pat: str) -> str:
    """gitignore 패턴 본문 하나를 정규식으로 (** / * / ? / [..] / \\x)."""
    i, n, out = 0, len(pat), []
    if pat.startswith("**/"):
        out.append("(?:.*/)?")
        i = 3
    while i < n:
        if pat.startswith("/**/", i):
            out.append("/(?:.*/)?")
            i += 4
            continue
        if pat.startswith("/**", i) and i + 3 == n:
            out.append("/.*")
            i += 3
            continue
        c = pat[i]
        if c == "*":
            while i < n and pat[i] == "*":
                i += 1
            out.append("[^/]*")
            continue
        if c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pat.find("]", i + 2)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = pat[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j
        elif c == "\\" and i + 1 < n:
            i += 1
            out.append(re.escape(pat[i]))
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


class IncludeMatcher:
    """.worktreeinclude (gitignore 문법) 판정기. 마지막으로 맞은 규칙이 이긴다. 디렉터리 패턴은 그 아래 전부."""

    def __init__(self, lines):
        self.rules: list[tuple[re.Pattern, bool, bool]] = []
        for raw in lines:
            line = raw.rstrip("\r\n")
            if not line.strip() or line.startswith("#"):
                continue
            line = re.sub(r"(?<!\\)\s+$", "", line)
            negate = line.startswith("!")
            if negate:
                line = line[1:]
            if line.startswith(("\\#", "\\!")):
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            if not line:
                continue
            anchored = "/" in line
            body = _translate(line.lstrip("/"))
            rx = body if anchored else "(?:.*/)?" + body
            self.rules.append((re.compile(rx, re.S), negate, dir_only))

    def match(self, rel: str) -> bool:
        parts = rel.split("/")
        result = False
        for rx, negate, dir_only in self.rules:
            for i in range(1, len(parts) + 1):
                if dir_only and i == len(parts):
                    continue
                if rx.fullmatch("/".join(parts[:i])):
                    result = not negate
                    break
        return result


def include_patterns(*roots: str) -> tuple[list[str], str]:
    for root in roots:
        f = os.path.join(root, ".worktreeinclude")
        if os.path.isfile(f):
            with open(f, encoding="utf-8", errors="replace") as fh:
                return fh.read().splitlines(), ".worktreeinclude"
    return list(DEFAULT_INCLUDE), "기본 목록"


def _under_skip_dir(rel: str, *, is_dir: bool) -> bool:
    parts = rel.split("/")
    return any(p in SKIP_DIRS for p in (parts if is_dir else parts[:-1]))


def walk_files(root: str, rel_dir: str, cap: int = 20000) -> list[str]:
    """rel_dir 아래 일반 파일 (링크·junction 을 따라가지 않고, 의존성·빌드 폴더와 중첩 저장소는 건너뛴다)."""
    found: list[str] = []
    stack = [rel_dir]
    while stack:
        rel = stack.pop()
        try:
            entries = list(os.scandir(join_rel(root, rel)))
        except OSError:
            continue
        for e in entries:
            r = f"{rel}/{e.name}"
            if entry_is_link(e):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if e.name in SKIP_DIRS or e.name == ".git" or os.path.lexists(os.path.join(e.path, ".git")):
                    continue
                stack.append(r)
            else:
                found.append(r)
                if len(found) >= cap:
                    return found
    return found


def check_ignored(root: str, rels: list[str]) -> set[str]:
    if not rels:
        return set()
    p = git(root, "check-ignore", "--stdin", "-z", check=False, input_text="\0".join(rels) + "\0")
    if p.returncode not in (0, 1):
        raise WtError("git check-ignore 실패", ERROR, _tail(p))
    return {x for x in p.stdout.split("\0") if x}


def find_include_files(root: str, patterns: list[str]) -> tuple[list[str], list[str]]:
    """root 에서 include 패턴에 맞고, git 이 무시(ignore)하는 1MB 이하 일반 파일. (파일 목록, 건너뛴 이유)"""
    matcher = IncludeMatcher(patterns)
    if not matcher.rules:
        return [], []
    p = git(root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory")
    cands: set[str] = set()
    for entry in p.stdout.split("\0"):
        if not entry:
            continue
        if entry.endswith("/"):
            d = entry.rstrip("/")
            if _under_skip_dir(d, is_dir=True) or os.path.lexists(os.path.join(join_rel(root, d), ".git")):
                continue
            cands.update(r for r in walk_files(root, d) if matcher.match(r))
        elif not _under_skip_dir(entry, is_dir=False) and matcher.match(entry):
            cands.add(entry)
    ignored = check_ignored(root, sorted(cands))
    files, skipped = [], []
    for rel in sorted(cands):
        full = join_rel(root, rel)
        if rel not in ignored:
            skipped.append(f"{rel} (ignore 대상 아님)")
        elif is_link(full) or not os.path.isfile(full):
            skipped.append(f"{rel} (링크 또는 일반 파일 아님)")
        elif os.path.getsize(full) > MAX_COPY_BYTES:
            skipped.append(f"{rel} ({os.path.getsize(full) // 1024}KB, 1MB 초과)")
        else:
            files.append(rel)
    return files, skipped


def copy_includes(src: str, dst: str) -> tuple[list[dict], list[str], str]:
    """메인의 ignored 로컬 설정을 새 worktree 로. 이미 있는 파일은 덮지 않는다 (재실행 안전)."""
    patterns, source = include_patterns(src)
    files, skipped = find_include_files(src, patterns)
    ok_dst = check_ignored(dst, files)
    copied = []
    for rel in files:
        if rel not in ok_dst:
            skipped.append(f"{rel} (새 worktree 에서는 ignore 대상이 아니라 복사 안 함)")
            continue
        d = join_rel(dst, rel)
        if os.path.lexists(d):
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(join_rel(src, rel), d)
        copied.append({"path": rel, "sha256": sha256_file(d), "size": os.path.getsize(d)})
    return copied, skipped, source


# ---------------------------------------------------------------- 의존성·포트

def _subdirs(root: str) -> list[str]:
    dirs = [""]
    try:
        for e in sorted(os.scandir(root), key=lambda e: e.name):
            if e.name.startswith(".") or e.name in SKIP_DIRS or entry_is_link(e):
                continue
            if e.is_dir(follow_symlinks=False) and not os.path.lexists(os.path.join(e.path, ".git")):
                dirs.append(e.name)
    except OSError:
        pass
    return dirs


def detect_installs(root: str) -> list[dict]:
    """lockfile 로 설치 명령을 고른다 (루트와 1단계 하위 폴더)."""
    items: list[dict] = []
    for d in _subdirs(root):
        base = join_rel(root, d) if d else root
        label = d or "."

        def has(name: str) -> bool:
            return os.path.isfile(os.path.join(base, name))

        for lock, cmd in JS_LOCKS:
            if has(lock):
                items.append({"dir": label, "file": lock, "cmd": cmd, "run": True})
                break
        if has("uv.lock"):
            items.append({"dir": label, "file": "uv.lock", "cmd": ["uv", "sync", "--frozen"], "run": True})
        else:
            try:
                reqs = sorted(n for n in os.listdir(base) if re.fullmatch(r"requirements.*\.txt", n))
            except OSError:
                reqs = []
            if reqs:
                hint = (f"python -m venv .venv; .venv\\Scripts\\python -m pip install -r {reqs[0]}" if IS_WINDOWS
                        else f"python3 -m venv .venv && .venv/bin/pip install -r {reqs[0]}")
                items.append({"dir": label, "file": reqs[0], "cmd": [], "hint": hint, "run": False})
        if any(has(n) for n in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "pom.xml")):
            items.append({"dir": label, "file": "gradle/maven", "cmd": [], "run": False,
                          "hint": "설치 없음 (첫 빌드가 ~/.gradle·~/.m2 캐시를 쓴다)"})
    return items


def install_text(it: dict) -> str:
    return " ".join(it["cmd"]) if it["cmd"] else it.get("hint", "")


def run_installs(items: list[dict], root: str, out: Out) -> list[dict]:
    results = []
    for it in items:
        if not it["run"]:
            continue
        exe = shutil.which(it["cmd"][0])
        if not exe:
            out.warn(f"{it['cmd'][0]} 이(가) PATH 에 없어 설치를 건너뛴다 ({it['dir']})")
            results.append({"dir": it["dir"], "cmd": install_text(it), "rc": None})
            continue
        cwd = root if it["dir"] == "." else join_rel(root, it["dir"])
        out.say(f"  $ (cd {q(cwd)}) {install_text(it)}")
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            p = subprocess.run([exe, *it["cmd"][1:]], cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=sys.stderr if out.json_mode else None, timeout=1800)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = -1
        if rc != 0:
            out.warn(f"설치 실패 (rc={rc}): {install_text(it)} — worktree 안에서 다시 실행한다")
        results.append({"dir": it["dir"], "cmd": install_text(it), "rc": rc})
    return results


def detect_port_kinds(root: str) -> list[str]:
    kinds: list[str] = []
    for d in _subdirs(root):
        base = join_rel(root, d) if d else root
        try:
            with open(os.path.join(base, "package.json"), encoding="utf-8", errors="replace") as f:
                pkg = f.read()
        except OSError:
            pkg = ""
        if '"vite"' in pkg:
            kinds.append("vite")
        if '"next"' in pkg or '"react-scripts"' in pkg:
            kinds.append("web")
        py = ""
        for n in ("pyproject.toml", "requirements.txt"):
            try:
                with open(os.path.join(base, n), encoding="utf-8", errors="replace") as f:
                    py += f.read().lower()
            except OSError:
                pass
        if os.path.isfile(os.path.join(base, "manage.py")) or any(w in py for w in ("fastapi", "uvicorn", "django", "flask")):
            kinds.append("api")
        if any(os.path.isfile(os.path.join(base, n)) for n in ("build.gradle", "build.gradle.kts", "pom.xml")):
            kinds.append("spring")
    return list(dict.fromkeys(kinds))


def suggest_ports(root: str, offset: int) -> dict:
    ports = {}
    for kind in detect_port_kinds(root) or list(PORT_BASES):
        port = PORT_BASES[kind] + offset * PORT_STRIDE
        while port in AVOID_PORTS:
            port += 5  # 같은 base 의 다른 오프셋(+10 간격)과 겹치지 않는다
        ports[kind] = port
    return ports


def next_port_offset(repo: Repo) -> int:
    used = {w.state.get("port_offset") for w in repo.linked if w.managed}
    n = 1
    while n in used:
        n += 1
    return n


def listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.2):
            return True
    except OSError:
        return False


def busy_ports(state: dict | None) -> list[int]:
    return [int(p) for p in ((state or {}).get("ports") or {}).values() if isinstance(p, int) and listening(p)]


@contextmanager
def repo_lock(common: str, wait: float = 30.0):
    """new 의 오프셋 배정과 worktree add 를 한 번에 한 프로세스만 (공용 .git 안의 잠금 파일)."""
    path = os.path.join(common, LOCK_NAME)
    deadline = time.time() + wait
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {now_iso()}".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > 600:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                refuse(f"다른 make-worktree 가 실행 중이다 (잠금: {path})")
            time.sleep(0.2)
    try:
        yield
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------- 병합 방식 신호

PR_UPPER = re.compile(r"(?<![A-Za-z])PRs?(?![A-Za-z])")
PR_WORDS = re.compile(r"pull[ -]?requests?|풀 ?리퀘스트|\bgh pr\b", re.I)
PR_NEG = re.compile(r"없음|없다|금지|안 ?(?:씀|쓴|만든)|쓰지 않|만들지 않|불필요|\bno PRs?\b|without (?:a )?PR|do(?:n't| not) (?:open|create|use)", re.I)
MERGE_SCRIPT = re.compile(r"finish-task|relay-hub|merge[- ]script|머지 스크립트|병합 스크립트", re.I)
DOC_FILES = ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md", "CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md")
PR_TEMPLATES = (".github/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE.md", "pull_request_template.md",
                "docs/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE")
GITHUB_URL = re.compile(r"^(?:https?://(?:[^@/]+@)?github\.com/|ssh://git@github\.com(?::\d+)?/|git@github\.com:)"
                        r"([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.I)


def parse_github(url: str | None) -> tuple[str, str] | None:
    m = GITHUB_URL.match((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def gh_usable() -> bool:
    return os.environ.get(NO_GH_ENV) != "1" and shutil.which("gh") is not None


def gh(*args: str, timeout: int = 30) -> subprocess.CompletedProcess | None:
    if not gh_usable():
        return None
    try:
        return run(["gh", *args], timeout=timeout)
    except WtError:
        return None


def gh_pr_view(gh_repo: str, branch: str) -> dict | None:
    p = gh("pr", "view", branch, "-R", gh_repo, "--json", "number,state,url,headRefOid")
    if not p or p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


def scan_docs(main_path: str) -> dict:
    """CLAUDE.md·AGENTS.md·CONTRIBUTING 과 상위 2단계 폴더의 CLAUDE.md·AGENTS.md 에서 PR·병합 절차 언급을 찾는다."""
    found = {"pr": [], "pr_negative": [], "custom": []}
    files = [(os.path.join(main_path, *n.split("/")), n) for n in DOC_FILES]
    parent = os.path.dirname(main_path.rstrip("\\/"))
    for up in (parent, os.path.dirname(parent)):
        if up and up != main_path:
            files += [(os.path.join(up, n), os.path.join(up, n)) for n in ("CLAUDE.md", "AGENTS.md")]
    seen = set()
    for path, label in files:
        if key(path) in seen or not os.path.isfile(path):
            continue
        seen.add(key(path))
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read(200_000)
        except OSError:
            continue
        for no, line in enumerate(text.splitlines(), 1):
            ev = f"{label}:{no}: {line.strip()[:110]}"
            if MERGE_SCRIPT.search(line):
                found["custom"].append(ev)
            elif PR_UPPER.search(line) or PR_WORDS.search(line):
                found["pr_negative" if PR_NEG.search(line) else "pr"].append(ev)
    for t in PR_TEMPLATES:
        if os.path.exists(os.path.join(main_path, *t.split("/"))):
            found["pr"].insert(0, f"PR 템플릿이 있다: {t}")
    return found


def collect_signals(repo: Repo, base: Base, *, full: bool = True) -> dict:
    """finish 방식 추천에 쓰는 저장소 신호. full=False 면 gh API·문서 읽기를 건너뛴다."""
    url = gout(repo.git_cwd, "config", "--get", "remote.origin.url", check=False) if repo.remote else ""
    gh_info = parse_github(url)
    shown_url = re.sub(r"(?<=//)[^/@\s]+@", "", url)  # URL 에 박힌 토큰·비밀번호는 출력하지 않는다
    sig: dict = {
        "origin": shown_url or None, "github": f"{gh_info[0]}/{gh_info[1]}" if gh_info else None,
        "owner": gh_info[0] if gh_info else None, "gh_usable": gh_usable(), "gh_user": None,
        "protected": None, "protected_detail": "", "pr_docs": [], "pr_docs_negative": [], "custom_merge_docs": [],
        "base_branch": base.branch, "base_holder": None, "main_dirty": None, "main_operation": None,
    }
    if base.branch:
        holder = next((w for w in repo.worktrees if w.branch == base.branch and w.prunable is None), None)
        sig["base_holder"] = holder.path if holder else None
    if not full:
        return sig
    main = repo.main
    if main.present and not main.bare:
        sig["main_dirty"] = len(dirty_lines(main.path))
        sig["main_operation"] = op_in_progress(main.path)
        docs = scan_docs(main.path)
        sig["pr_docs"], sig["pr_docs_negative"], sig["custom_merge_docs"] = docs["pr"], docs["pr_negative"], docs["custom"]
    if gh_info and sig["gh_usable"]:
        p = gh("api", "user", "--jq", ".login")
        if p and p.returncode == 0 and p.stdout.strip():
            sig["gh_user"] = p.stdout.strip()
        if sig["gh_user"] and base.branch:
            o, r = gh_info
            b = urllib.parse.quote(base.branch, safe="")
            p = gh("api", f"repos/{o}/{r}/branches/{b}/protection")
            if p and p.returncode == 0:
                sig["protected"], sig["protected_detail"] = True, "branch protection"
            elif p and "Branch not protected" in (p.stdout + p.stderr):
                sig["protected"] = False
            p = gh("api", f"repos/{o}/{r}/rules/branches/{b}")
            if p and p.returncode == 0:
                try:
                    types = sorted({str(x.get("type")) for x in json.loads(p.stdout or "[]") if isinstance(x, dict)})
                except ValueError:
                    types = []
                if "pull_request" in types:
                    sig["protected"] = True
                    sig["protected_detail"] = ", ".join(filter(None, [sig["protected_detail"], "ruleset: " + ", ".join(types)]))
                elif sig["protected"] is None:
                    sig["protected"] = False if not types else None
    return sig


def recommend_mode(sig: dict) -> tuple[str, list[str]]:
    """신호 → (pr|push|local|delegate, 이유들). 정하는 것은 사용자다 — 이 결과는 추천일 뿐이다."""
    if sig.get("custom_merge_docs"):
        return "delegate", ["저장소 문서에 자체 병합 절차가 있다: " + sig["custom_merge_docs"][0],
                            "그 절차를 따르고 finish 는 쓰지 않는다"]
    if not sig.get("origin"):
        reasons = ["origin 원격이 없다 — 로컬 브랜치끼리 합친다"]
        if sig.get("base_holder"):
            reasons.append(f"base 브랜치가 {sig['base_holder']} 에 checkout 돼 있어 그 폴더는 건드리지 않고, 한가할 때 실행할 한 줄을 안내한다")
        return "local", reasons
    if not sig.get("github"):
        if sig.get("pr_docs"):
            return "delegate", ["origin 이 GitHub 이 아니라 gh 로 PR 을 만들 수 없는데 문서가 PR 을 언급한다 — " + sig["pr_docs"][0],
                                "그 원격 서비스의 PR(merge request) 절차를 따른다"]
        return "push", ["origin 이 GitHub 이 아니라 gh 로 PR 을 만들 수 없고 문서에도 PR 언급이 없다",
                        "원격 서비스가 PR(merge request)을 요구하면 그 절차를 따른다(delegate)"]
    votes = []
    if sig.get("protected"):
        votes.append(f"base 브랜치 보호·규칙이 있다 ({sig.get('protected_detail') or '보호'})")
    if sig.get("pr_docs"):
        votes.append("저장소 문서가 PR 을 언급한다 — " + sig["pr_docs"][0])
    if sig.get("gh_user") and sig.get("owner") and sig["gh_user"].lower() != sig["owner"].lower():
        votes.append(f"저장소 소유자({sig['owner']})가 gh 사용자({sig['gh_user']})와 다르다 (협업 저장소)")
    if votes:
        if not sig.get("gh_user"):
            votes.append("단 gh 설치·로그인이 필요하다 (gh auth login)")
        return "pr", votes
    if not sig.get("gh_user"):
        return "push", ["gh 를 쓸 수 없어(설치·로그인) 보호 규칙·소유자를 확인하지 못했다 — 협업 저장소면 pr 을 고른다"]
    reasons = [f"개인 저장소(소유자 {sig['owner']} = gh 사용자)이고 base 보호·PR 규칙·문서의 PR 언급이 없다"]
    if sig.get("protected") is None:
        reasons.append("브랜치 보호 여부는 확인하지 못했다")
    if sig.get("pr_docs_negative"):
        reasons.append("문서가 PR 을 쓰지 않는다고 적었다 — " + sig["pr_docs_negative"][0])
    return "push", reasons


def render_signals(sig: dict) -> str:
    parts = []
    if not sig.get("origin"):
        parts.append("origin 없음")
    elif sig.get("github"):
        parts.append(f"origin GitHub {sig['github']}")
    else:
        parts.append(f"origin {sig['origin']} (GitHub 아님)")
    if sig.get("github"):
        if sig.get("gh_user"):
            same = sig["owner"] and sig["gh_user"].lower() == sig["owner"].lower()
            parts.append(f"gh {sig['gh_user']} ({'소유자와 같음' if same else '소유자와 다름'})")
        else:
            parts.append("gh 사용 불가")
        parts.append({True: f"보호 있음({sig.get('protected_detail')})", False: "보호 없음"}.get(sig.get("protected"), "보호 확인 불가"))
    if sig.get("custom_merge_docs"):
        parts.append("문서에 병합 절차")
    parts.append("문서 PR 언급 " + (f"{len(sig['pr_docs'])}곳" if sig.get("pr_docs") else "없음"))
    if sig.get("main_dirty") is not None:
        parts.append(f"메인 dirty {sig['main_dirty']}" + (f", {sig['main_operation']} 진행 중" if sig.get("main_operation") else ""))
    return " · ".join(parts)


# ---------------------------------------------------------------- 브랜치·worktree 분석

def branch_info(repo: Repo, branch: str | None, base: Base, state: dict | None, sig: dict | None) -> dict:
    """머지·push 여부. merged 는 '커밋이 1개 이상 있고 base 에 들어갔다' 이다 (갓 만든 빈 브랜치는 merged 아님)."""
    info = {"name": branch, "exists": False, "tip": None, "commits": 0, "merged": False, "merged_via": None,
            "unsafe": 0, "upstream": None, "pushed": False, "pr": None}
    if not branch:
        return info
    cwd, full = repo.git_cwd, f"refs/heads/{branch}"
    info["tip"] = rev(cwd, full)
    if not info["tip"]:
        return info
    info["exists"] = True
    base_ref = base.ref if rev(cwd, base.ref) else None
    created = (state or {}).get("base_commit")
    if created and rev(cwd, created):
        info["commits"] = count(cwd, f"{created}..{full}")
    elif base_ref:
        info["commits"] = count(cwd, f"{base_ref}..{full}")
    if base_ref and info["commits"] > 0 and is_ancestor(cwd, full, base_ref):
        info["merged"], info["merged_via"] = True, "ancestor"
    if repo.remote:
        excl = ["--remotes"] + ([base_ref] if base_ref else [])
        if base.branch and ref_exists(cwd, f"refs/heads/{base.branch}"):
            excl.append(f"refs/heads/{base.branch}")
    else:
        excl = [f"--exclude={branch}", "--branches"]  # --branches 앞의 --exclude 는 refs/heads/ 를 빼고 쓴다
    info["unsafe"] = count(cwd, full, "--not", *excl, strict=True)
    info["upstream"] = gout(cwd, "for-each-ref", "--format=%(upstream:short)", full) or None
    info["pushed"] = bool(repo.remote and ref_exists(cwd, f"refs/remotes/{repo.remote}/{branch}"))
    finished_pr = ((state or {}).get("finish") or {}).get("mode") == "pr"
    if (not info["merged"] and sig and sig.get("github") and sig.get("gh_usable")
            and (info["pushed"] or info["upstream"] or finished_pr)):
        pr = gh_pr_view(sig["github"], branch)
        if pr:
            info["pr"] = pr
            if pr.get("state") == "MERGED" and (pr.get("headRefOid") == info["tip"] or info["unsafe"] == 0):
                info["merged"], info["merged_via"] = True, "pr"
    return info


def analyze(repo: Repo, w: WT, sig: dict | None) -> dict:
    st = w.state or {}
    base = base_for(repo, w)
    row = {"path": w.path, "managed": w.managed, "main": w.is_main, "slug": st.get("slug") if w.managed else None,
           "branch": w.branch, "detached": w.detached, "head": (w.head or "")[:10], "base": base.ref,
           "dirty": None, "ahead": None, "behind": None, "commits": 0, "merged": False, "merged_via": None,
           "upstream": None, "unpushed": None, "pr": None, "last_commit": None, "locked": w.locked,
           "prunable": w.prunable, "is_cwd": False, "port_offset": st.get("port_offset"), "ports": st.get("ports"),
           "finish": st.get("finish"), "flags": []}
    if w.present and not w.bare:
        row["dirty"] = len(dirty_lines(w.path))
        row["is_cwd"] = inside(os.getcwd(), w.path)
        if base.ref and rev(w.path, base.ref):
            row["behind"], row["ahead"] = left_right(w.path, base.ref)
        row["last_commit"] = gout(w.path, "log", "-1", "--format=%cI", check=False) or None
    branch = w.branch or st.get("branch")
    row["branch"] = branch
    if not w.is_main:
        bi = branch_info(repo, branch, base, st, sig)
        row.update({"commits": bi["commits"], "merged": bi["merged"], "merged_via": bi["merged_via"],
                    "upstream": bi["upstream"], "pr": bi["pr"]})
        if repo.remote and bi["exists"]:
            row["unpushed"] = bi["unsafe"]
    flags = row["flags"]
    if w.is_main:
        flags.append("MAIN")
    if w.prunable is not None:
        flags.append("PRUNABLE")
    if row["dirty"]:
        flags.append("DIRTY")
    if row["merged"] and not row["dirty"] and not w.is_main:
        flags.append("MERGED→remove")
    if not row["merged"] and row["unpushed"]:
        flags.append(f"UNPUSHED {row['unpushed']}")
    if not row["merged"] and row["behind"]:
        flags.append(f"BEHIND {row['behind']}")
    if row["pr"] and row["pr"].get("state") == "OPEN":
        flags.append(f"PR #{row['pr'].get('number')} OPEN")
    fin = row["finish"] or {}
    if fin.get("mode") == "local" and fin.get("deferred") and not row["merged"]:
        flags.append("LOCAL-PENDING")
    if w.locked is not None:
        flags.append("LOCKED")
    if row["is_cwd"]:
        flags.append("CWD")
    return row


def find_leftovers(repo: Repo) -> list[str]:
    """<repo>.wt 안에 남았지만 worktree 로 등록돼 있지 않은 폴더 (점으로 시작하는 .backup 등은 제외)."""
    if not os.path.isdir(repo.wt_root):
        return []
    registered = {key(w.path) for w in repo.worktrees}
    res = []
    for e in os.scandir(repo.wt_root):
        if not e.name.startswith(".") and e.is_dir(follow_symlinks=False) and key(e.path) not in registered:
            res.append(display(e.path))
    return sorted(res)


def has_regular_files(root: str) -> bool:
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if entry_is_link(e):
                continue
            if e.is_dir(follow_symlinks=False):
                stack.append(e.path)
            else:
                return True
    return False


def find_links(root: str) -> list[str]:
    """root 아래 junction·symlink (따라 들어가지 않는다). os.walk 는 junction 을 따라가므로 직접 걷는다."""
    links, stack = [], [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if entry_is_link(e):
                links.append(e.path)
                continue
            try:
                if e.is_dir(follow_symlinks=False) and e.name != ".git":
                    stack.append(e.path)
            except OSError:
                pass
    return links


def tracked_links(wt_path: str) -> set[str]:
    """저장소가 추적하는 symlink (mode 120000). 이것은 git 이 지우므로 건드리지 않는다 (지우면 dirty 가 된다)."""
    res = set()
    for entry in gout(wt_path, "ls-files", "-s", "-z").split("\0"):
        meta, _, rel = entry.partition("\t")
        if meta.startswith("120000 ") and rel:
            res.add(key(join_rel(wt_path, rel)))
    return res


def unlink_links(root: str, out: Out, keep: set[str] | None = None) -> int:
    """junction·symlink 를 해제한다 (대상은 건드리지 않는다). keep 에 든 경로는 남긴다."""
    n = 0
    for p in find_links(root):
        if keep and key(p) in keep:
            continue
        try:
            os.unlink(p)
        except OSError:
            try:
                os.rmdir(p)
            except OSError as e:
                out.warn(f"링크를 해제하지 못했다: {p} ({e})")
                continue
        n += 1
    return n


def remove_empty_root(repo: Repo) -> bool:
    try:
        if os.path.isdir(repo.wt_root) and not os.listdir(repo.wt_root):
            os.rmdir(repo.wt_root)
            return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------- new

def enter_hints(path: str) -> dict:
    hints = {"EnterWorktree": f'EnterWorktree(path="{path}")'}
    if IS_WINDOWS:
        hints["wt"] = f'wt -w 0 nt -d "{path}" pwsh -NoExit -Command claude'
    hints["code"] = f'code -n "{path}"'
    hints["cd"] = f'cd "{path}"'
    return hints


def warn_long_paths(repo: Repo, path: str, commit: str, out: Out) -> None:
    if not IS_WINDOWS:
        return
    p = git(repo.git_cwd, "ls-tree", "-r", "-z", "--name-only", commit, check=False)
    longest = max((len(n) for n in p.stdout.split("\0") if n), default=0)
    total = len(path) + 1 + longest
    if total >= 240:
        lp = gout(repo.git_cwd, "config", "--get", "core.longpaths", check=False) or "설정 안 됨"
        out.warn(f"가장 긴 파일 경로가 {total}자다 (Windows 기본 한도 260자). slug 를 줄이거나 core.longpaths 를 확인한다 (지금: {lp})")


def resolve_new_base(repo: Repo, args) -> tuple[Base, str, str]:
    """(통합 대상 base, 사람용 설명, 시작 커밋)."""
    main = repo.main
    if args.from_head:
        if main.bare or not main.present:
            refuse("--from-head: 메인 worktree 에 체크아웃이 없다")
        commit = rev(main.path, "HEAD")
        if main.branch and repo.remote and ref_exists(repo.git_cwd, f"refs/remotes/{repo.remote}/{main.branch}"):
            base = Base(main.branch, repo.remote)
        elif main.branch and not repo.remote:
            base = Base(main.branch, None)
        else:
            base = default_base(repo)
        return base, f"메인 HEAD ({main.branch or 'detached'}, 커밋된 상태만)", commit
    if args.base:
        commit = None
        try:
            base = make_base(repo, args.base)
            commit = rev(repo.git_cwd, base.ref)
        except WtError:
            commit = rev(repo.git_cwd, args.base)
            if not commit:
                refuse(f"--base 를 찾지 못했다: {args.base}")
            base = default_base(repo)
        return base, args.base, commit
    if repo.remote:
        base = default_base(repo)
        return base, base.ref, rev(repo.git_cwd, base.ref)
    if main.bare or not main.branch:
        refuse("원격이 없고 메인 worktree 에 브랜치가 없다 — --base 로 지정한다")
    return Base(main.branch, None), f"{main.branch} (메인 HEAD, 원격 없음)", rev(main.path, "HEAD")


def cmd_new(repo: Repo, args, out: Out) -> int:
    slug = args.slug
    if not SLUG_RE.match(slug) or len(slug) > SLUG_MAX:
        refuse(f"slug 는 영어 소문자·숫자·하이픈(kebab-case), {SLUG_MAX}자 이하다: {slug!r}", ["예: login-fix, api-timeout"])
    path = os.path.join(repo.wt_root, slug)
    w = repo.find(path)
    if w is not None:
        if not w.present:
            refuse(f"폴더 없이 메타데이터만 남은 worktree 가 있다: {path}", [f"정리: python {q(SELF)} remove {slug}"])
        if not w.managed:
            refuse(f"make-worktree 가 만들지 않은 worktree 가 이미 있다: {path}")
        out.say(f"이미 있다 — 그대로 쓴다: {path}")
        return report_new(repo, w, args, out, reused=True)
    if os.path.lexists(path):
        refuse(f"폴더가 이미 있다 (worktree 아님): {path}")
    branch = args.branch or f"wt/{slug}"
    if not gok(repo.git_cwd, "check-ref-format", "--branch", branch):
        refuse(f"브랜치 이름이 올바르지 않다: {qb(branch)}")
    if ref_exists(repo.git_cwd, f"refs/heads/{branch}"):
        refuse(f"브랜치가 이미 있다: {qb(branch)}", ["다른 slug 를 쓰거나 --branch 로 새 이름을 준다"])
    if repo.remote and ref_exists(repo.git_cwd, f"refs/remotes/{repo.remote}/{branch}"):
        refuse(f"원격에 같은 이름의 브랜치가 있다: {repo.remote}/{branch}")
    out.say(f"make-worktree new: {slug}")
    if repo.remote and not args.no_fetch:
        fetch(repo.git_cwd, out, write_fetch_head=False)
    base, label, commit = resolve_new_base(repo, args)
    if not commit:
        refuse(f"base 커밋을 찾지 못했다: {label}")
    warn_long_paths(repo, path, commit, out)
    made_root = not os.path.isdir(repo.wt_root)
    with repo_lock(repo.common):
        offset = next_port_offset(load_repo(repo.git_cwd))
        os.makedirs(repo.wt_root, exist_ok=True)
        p = step(out, repo.git_cwd, ["worktree", "add", "--no-track", "-b", branch, path, commit], check=False,
                 timeout=900, branch=branch)
        if p.returncode != 0:
            if made_root:
                remove_empty_root(repo)
            raise WtError("git worktree add 실패", ERROR, _tail(p))
        state = {"tool": TOOL, "version": 1, "slug": slug, "branch": branch, "base": label,
                 "base_branch": base.branch, "remote": base.remote, "base_commit": commit,
                 "created_at": now_iso(), "port_offset": offset, "ports": suggest_ports(path, offset),
                 "main": repo.main.path, "copied": []}
        write_json(state_path_of(path), state)
    w = load_repo(repo.git_cwd).find(path)
    return report_new(repo, w, args, out, reused=False)


def report_new(repo: Repo, w: WT, args, out: Out, *, reused: bool) -> int:
    st = dict(w.state or {})
    copied_now, skipped, source = [], [], "-"
    if not args.no_copy and repo.main.present and not repo.main.bare:
        copied_now, skipped, source = copy_includes(repo.main.path, w.path)
        if copied_now:
            have = {c.get("path") for c in st.get("copied", [])}
            st["copied"] = st.get("copied", []) + [c for c in copied_now if c["path"] not in have]
            save_state(w, st)
    installs = detect_installs(w.path)
    results = run_installs(installs, w.path, out) if args.install else None
    hints = enter_hints(w.path)
    base_commit = st.get("base_commit", "")
    subject = gout(w.path, "log", "-1", "--format=%h %cs %s", base_commit, check=False) if base_commit else ""
    ports = st.get("ports") or {}
    out.say("")
    out.say(f"  경로     {w.path}")
    branch = st.get("branch") or w.branch or ""
    upstream = gout(w.path, "for-each-ref", "--format=%(upstream:short)", f"refs/heads/{branch}", check=False)
    out.say(f"  브랜치   {qb(branch)}  " + (f"(upstream {upstream})" if upstream else "(upstream 없음 — pr 모드의 첫 push 때 -u)"))
    target = Base(st.get("base_branch"), st.get("remote")).ref
    label = target if st.get("base") == target else f"{st.get('base')} (통합 대상 {target})"
    out.say(f"  base     {label} @ {subject}")
    out.say(f"  포트     오프셋 {st.get('port_offset')} → " + " · ".join(f"{k} {v}" for k, v in ports.items())
            + f"  (기본 포트 + {PORT_STRIDE}×오프셋, 8000·8001 제외)")
    all_copied = [c["path"] for c in st.get("copied", [])]
    out.say(f"  복사     {', '.join(all_copied) if all_copied else '없음'}  (ignored 로컬 설정, 패턴: {source})")
    for s in skipped[:10]:
        out.say(f"           건너뜀: {s}")
    if installs:
        for it in installs:
            tag = "" if it["run"] else "  [직접]"
            out.say(f"  설치     ({it['dir']}) {install_text(it)}{tag}")
        if results is None and any(it["run"] for it in installs):
            out.say("           → 빌드·테스트가 필요하면 --install 로 다시 실행하거나 worktree 안에서 위 명령을 실행한다")
    else:
        out.say("  설치     lockfile 없음")
    out.say("들어가기:")
    out.say(f"  Claude Code 세션 이동  {hints['EnterWorktree']}")
    if "wt" in hints:
        out.say(f"  새 터미널 탭          {hints['wt']}")
    out.say(f"  VS Code 새 창         {hints['code']}")
    out.say(f"  다른 에이전트·셸      {hints['cd']}")
    out.say(f"끝나면: python {q(SELF)} sync → 검증(테스트·빌드) → finish --mode <pr|push|local> → remove {st.get('slug')} --delete-branch")
    out.say(f"WORKTREE: {w.path}")
    out.data.update({"command": "new", "reused": reused, "worktree": w.path, "branch": st.get("branch"),
                     "base": st.get("base"), "base_ref": Base(st.get("base_branch"), st.get("remote")).ref,
                     "base_commit": base_commit, "port_offset": st.get("port_offset"), "ports": ports,
                     "copied": all_copied, "skipped": skipped, "include_source": source,
                     "install": [{"dir": it["dir"], "cmd": install_text(it), "auto": it["run"]} for it in installs],
                     "install_results": results, "enter": hints, "state_file": state_path_of(w.path)})
    return OK


# ---------------------------------------------------------------- status

def cmd_status(repo: Repo, args, out: Out) -> int:
    if args.fetch and repo.remote:
        fetch(repo.git_cwd, out, write_fetch_head=False)
    base = default_base(repo, soft=True)
    sig = collect_signals(repo, base)
    mode, reasons = recommend_mode(sig)
    rows = []
    for w in repo.worktrees:
        if args.all or (not w.is_main and w.managed):
            rows.append(analyze(repo, w, sig))
    unmanaged = [w for w in repo.linked if not w.managed]
    leftovers = find_leftovers(repo)
    out.say(f"make-worktree status — {repo.name}")
    out.say(f"  메인    {repo.main.path}  ({qb(repo.main.branch) if repo.main.branch else 'detached'})")
    out.say(f"  폴더    {repo.wt_root}")
    out.say(f"  base    {base.ref or '(모름)'}")
    out.say(f"  신호    {render_signals(sig)}")
    out.say(f"  추천    finish 방식 = {mode}")
    for r in reasons:
        out.say(f"          - {r}")
    out.say("          (합칠 때 이 추천과 이유를 보여 주고 사용자에게 방식을 묻는다)")
    out.say("")
    managed_rows = [r for r in rows if r["managed"]]
    out.say(f"make-worktree worktree {len(managed_rows)}개" + ("" if rows else " — 없음"))
    for r in rows:
        name = r["slug"] or ("메인" if r["main"] else "관리 밖")
        br = qb(r["branch"]) if r["branch"] and not r["detached"] else f"detached @ {r['head']}"
        ab = f"+{r['ahead']}/-{r['behind']}" if r["ahead"] is not None else "+?/-?"
        dirty = "-" if r["dirty"] is None else r["dirty"]
        extra = [f"커밋 {r['commits']}"] if not r["main"] else []
        if not r["main"]:
            extra.append(f"upstream {r['upstream']}" if r["upstream"] else "upstream 없음")
        extra.append(ago(r["last_commit"]))
        if r["port_offset"]:
            extra.append(f"포트 +{r['port_offset']}")
        out.say(f"  [{name}] {br}  {ab}  dirty {dirty}  " + "  ".join(extra))
        out.say(f"      {r['path']}")
        if r["flags"]:
            out.say(f"      {' · '.join(r['flags'])}")
        fin = r["finish"] or {}
        if r["pr"]:
            out.say(f"      PR #{r['pr'].get('number')} {r['pr'].get('state')} {r['pr'].get('url')}")
        elif fin.get("mode") == "pr":
            out.say(f"      finish pr: {fin.get('pr_url')} ({ago(fin.get('at'))})")
        elif fin.get("mode") == "local" and fin.get("deferred") and not r["merged"]:
            out.say(f"      finish local 대기: {fin.get('holder')} 가 한가할 때 merge --no-ff {qb(r['branch'] or '')}")
        elif fin.get("mode"):
            out.say(f"      finish {fin.get('mode')} ({ago(fin.get('at'))})")
    if not args.all and unmanaged:
        prunable = sum(1 for w in unmanaged if w.prunable is not None)
        out.say(f"관리 밖 linked worktree {len(unmanaged)}개" + (f" (PRUNABLE {prunable})" if prunable else "") + " — --all 로 본다")
    for d in leftovers:
        out.say(f"  LEFTOVER (등록 안 된 폴더) {d}")
    if any("MERGED→remove" in r["flags"] for r in rows) or leftovers:
        out.say(f"정리: python {q(SELF)} clean   (dry-run 으로 목록을 보고 확인 후 --yes)")
    out.data.update({"command": "status", "repo": {"name": repo.name, "main": repo.main.path, "wt_root": repo.wt_root,
                                                   "base": base.ref, "remote": repo.remote},
                     "signals": sig, "recommend": {"mode": mode, "reasons": reasons}, "worktrees": rows,
                     "unmanaged": len(unmanaged), "leftovers": leftovers})
    return OK


# ---------------------------------------------------------------- sync

def conflict_error(op: str, w: WT, files: list[str]) -> WtError:
    if op == "rebase":
        hints = [f"해결: 파일을 고친 뒤 git -C {q(w.path)} add <파일> → git -C {q(w.path)} -c core.editor=true rebase --continue → sync 다시",
                 f"포기: git -C {q(w.path)} rebase --abort"]
    else:
        hints = [f"해결: 파일을 고친 뒤 git -C {q(w.path)} add <파일> → git -C {q(w.path)} commit --no-edit → sync 다시",
                 f"포기: git -C {q(w.path)} merge --abort"]
    hints.append("충돌은 이 worktree 안에서만 푼다 (메인 폴더에서 풀지 않는다)")
    return WtError(f"{op} 충돌 {len(files)}개 — worktree 안에서 푼다", CONFLICT, [f"충돌: {f}" for f in files] + hints)


def cmd_sync(repo: Repo, args, out: Out) -> int:
    w = resolve_target(repo, args.target)
    if w.is_main:
        refuse("메인 worktree 는 sync 대상이 아니다 (메인은 건드리지 않는다)")
    op = op_in_progress(w.path)
    if op:
        files = conflicted(w.path)
        if files:
            out.data["conflicts"] = files
            raise conflict_error(op, w, files)
        refuse(f"{op} 이(가) 진행 중이다 — 충돌을 다 풀었으면 커밋(rebase 는 --continue)한 뒤 sync 를 다시 실행한다")
    if w.detached or not w.branch:
        refuse("브랜치 위가 아니다 (detached) — 이미 끝난 worktree 면 remove 한다")
    dirty = dirty_lines(w.path)
    if dirty:
        refuse(f"커밋 안 된 변경 {len(dirty)}개 — 먼저 커밋한다", dirty[:20])
    base = base_for(repo, w, args.base)
    if not base.ref:
        refuse("base 브랜치를 모른다 — --base 로 지정한다")
    out.say(f"sync: {qb(w.branch)} ← {base.ref}")
    if base.remote and not args.no_fetch:
        fetch(w.path, out)
    if not rev(w.path, base.ref):
        refuse(f"base 를 찾지 못했다: {base.ref}")
    behind, ahead = left_right(w.path, base.ref)
    if behind == 0:
        out.say(f"이미 최신이다 (+{ahead}/-0). 다음: 검증(테스트·빌드) → finish")
        out.data.update({"command": "sync", "worktree": w.path, "base": base.ref, "ahead": ahead, "behind": 0, "changed": False})
        return OK
    if args.rebase:
        pushed = repo.remote and ref_exists(w.path, f"refs/remotes/{repo.remote}/{w.branch}")
        upstream = gout(w.path, "for-each-ref", "--format=%(upstream:short)", f"refs/heads/{w.branch}")
        if pushed or upstream:
            refuse("이미 push 한 브랜치는 rebase 하지 않는다 — --rebase 없이 merge 로 동기화한다")
        p = step(out, w.path, ["rebase", base.ref], check=False)
        op = "rebase"
    else:
        p = step(out, w.path, ["merge", "--no-edit", base.ref], check=False)
        op = "merge"
    if p.returncode != 0:
        files = conflicted(w.path)
        if files:
            out.data["conflicts"] = files
            raise conflict_error(op, w, files)
        raise WtError(f"{op} 실패", ERROR, _tail(p))
    behind2, ahead2 = left_right(w.path, base.ref)
    out.say(f"동기화했다: base 커밋 {behind}개 반영 ({op}). 지금 +{ahead2}/-{behind2}")
    out.say("다음: worktree 안에서 검증(테스트·빌드) → 통과하면 finish")
    out.data.update({"command": "sync", "worktree": w.path, "base": base.ref, "method": op, "applied": behind,
                     "ahead": ahead2, "behind": behind2, "changed": True})
    return OK


# ---------------------------------------------------------------- finish

def build_pr_create_cmd(gh_repo: str, base_branch: str, head: str, title: str | None = None,
                        body_file: str | None = None, default_title: str | None = None) -> list[str]:
    cmd = ["gh", "pr", "create", "-R", gh_repo, "--base", base_branch, "--head", head]
    if title or body_file:
        cmd += ["--title", title or default_title or head]
        cmd += ["--body-file", body_file] if body_file else ["--body", ""]
    else:
        cmd.append("--fill")
    return cmd


def merge_message_args(branch: str, base_branch: str, args) -> list[str]:
    msg = ["-m", args.title or f"Merge branch '{branch}' into {base_branch}"]
    if args.body_file:
        with open(args.body_file, encoding="utf-8", errors="replace") as f:
            body = f.read().strip()
        if body:
            msg += ["-m", body]
    return msg


def push_rejection(p: subprocess.CompletedProcess) -> str | None:
    """push 실패 종류: "protected"(보호 규칙이 거부 — 재시도해도 소용없다), "race"(원격이 그사이 움직였다), None."""
    text = (p.stderr or "") + (p.stdout or "")
    if re.search(r"protected branch|GH006|GH013|declined|pull request", text, re.I):
        return "protected"
    if re.search(r"rejected|non-fast-forward|fetch first|stale info|cannot lock ref|failed to update ref", text, re.I):
        return "race"
    return None


def changed_includes(w: WT) -> list[str]:
    res = []
    for c in (w.state or {}).get("copied", []):
        f = join_rel(w.path, c.get("path", ""))
        if os.path.isfile(f) and sha256_file(f) != c.get("sha256"):
            res.append(c["path"])
    return res


def cmd_finish(repo: Repo, args, out: Out) -> int:
    w = resolve_target(repo, args.target)
    if w.is_main:
        refuse("메인 worktree 에서는 finish 하지 않는다 — 끝낼 worktree 의 slug 나 경로를 준다")
    st = dict(w.state or {})
    base = base_for(repo, w, args.base)
    if not base.branch:
        refuse("base 브랜치를 모른다 — --base 로 지정한다")
    out.data.update({"command": "finish", "worktree": w.path, "mode": args.mode, "dry_run": args.dry_run})
    if w.detached or not w.branch:
        bi = branch_info(repo, st.get("branch"), base, st, collect_signals(repo, base, full=False))
        if st.get("finish") and bi["merged"]:
            out.say(f"이미 끝났다 ({st['finish'].get('mode')}): {qb(st.get('branch', ''))} 는 {base.ref} 에 들어갔다")
            out.say(f"다음: python {q(SELF)} remove {st.get('slug')} --delete-branch")
            out.data["already"] = True
            return OK
        refuse("브랜치 위가 아니다 (detached)")
    branch = w.branch
    if st.get("branch") and st["branch"] != branch:
        out.warn(f"worktree 의 브랜치가 만들 때({st['branch']})와 다르다 — 지금 브랜치 {branch} 로 진행한다")
    op = op_in_progress(w.path)
    if op:
        refuse(f"{op} 이(가) 진행 중이다 — 끝낸 뒤 다시")
    dirty = dirty_lines(w.path)
    if dirty:
        refuse(f"커밋 안 된 변경 {len(dirty)}개 — 커밋하거나 버린 뒤 다시 (스크립트는 대신 커밋하지 않는다)", dirty[:20])
    local_mode = args.mode == "local"
    target = base.branch if local_mode else base.ref
    out.say(f"finish ({args.mode or '점검'}{', dry-run' if args.dry_run else ''}): {qb(branch)} → {target}")
    if base.remote and not args.no_fetch and not local_mode:
        fetch(w.path, out)
    if not rev(w.path, target):
        refuse(f"base 를 찾지 못했다: {target}")
    ahead = count(w.path, f"{target}..HEAD")
    if ahead == 0:
        created = st.get("base_commit")
        if created and count(w.path, f"{created}..HEAD") > 0 and is_ancestor(w.path, "HEAD", target):
            out.say(f"이미 {target} 에 들어가 있다 — 합칠 것이 없다. 다음: remove {st.get('slug', '')} --delete-branch")
            out.data["already"] = True
            return OK
        refuse(f"{target} 에 없는 커밋이 없다 — 합칠 것이 없다 (작업을 커밋했는지 확인한다)")
    if not is_ancestor(w.path, target, "HEAD"):
        refuse(f"{target} 에 새 커밋이 있다 — 먼저 sync 하고 다시 검증한 뒤 finish 한다",
               [f"python {q(SELF)} sync {q(w.path)}"])
    for port in busy_ports(st):
        out.warn(f"포트 {port} 에서 무언가 LISTEN 중이다 — 이 worktree 의 dev 서버라면 끈다 (remove 때 파일 잠금)")
    changed = changed_includes(w)
    if changed:
        out.warn("worktree 에서 바뀐 ignored 설정은 병합되지 않는다 (remove 때 백업): " + ", ".join(changed))
    if not args.mode:
        sig = collect_signals(repo, base)
        mode, reasons = recommend_mode(sig)
        out.say(f"점검 통과: 커밋 {ahead}개, base 와 동기화됨, clean")
        out.say(f"신호: {render_signals(sig)}")
        out.say(f"추천: --mode {mode}")
        for r in reasons:
            out.say(f"  - {r}")
        out.say("아무것도 바꾸지 않았다. 사용자에게 방식을 확인한 뒤 --mode pr|push|local 로 다시 실행한다"
                + (" (delegate 면 문서의 절차를 따른다)" if mode == "delegate" else ""))
        out.data.update({"ready": True, "ahead": ahead, "signals": sig, "recommend": {"mode": mode, "reasons": reasons}})
        return OK
    if args.body_file:
        args.body_file = display(args.body_file)
        if not os.path.isfile(args.body_file):
            refuse(f"--body-file 이 없다: {args.body_file}")
    out.say(f"점검 통과: 커밋 {ahead}개, base 와 동기화됨, clean")
    if args.mode == "pr":
        return finish_pr(repo, w, branch, base, args, out)
    if args.mode == "push":
        return finish_push(repo, w, branch, base, args, out)
    return finish_local(repo, w, branch, base, args, out)


def _main_followup(repo: Repo, base: Base, out: Out) -> None:
    holder = next((x for x in repo.worktrees if x.branch == base.branch and x.prunable is None), None)
    if holder and holder.is_main:
        line = f"git -C {q(holder.path)} pull --ff-only"
        out.say(f"메인 폴더   건드리지 않았다. 한가할 때: {line}")
        out.data["main_followup"] = line
    elif holder:
        out.say(f"참고       {base.branch} 은(는) {holder.path} 에 checkout 돼 있다 — 그 폴더가 한가할 때 pull --ff-only")
    else:
        out.say("메인 폴더   건드리지 않았다 (base 브랜치가 checkout 돼 있지 않아 할 일 없음)")


def finish_push(repo: Repo, w: WT, branch: str, base: Base, args, out: Out) -> int:
    if not base.remote:
        refuse("origin 이 없다 — push 모드를 쓸 수 없다 (local 모드)")
    ref = base.ref
    msg = merge_message_args(branch, base.branch, args)
    plan = [["switch", "--detach", ref], ["merge", "--no-ff", "--no-edit", *msg, branch],
            ["push", base.remote, f"HEAD:refs/heads/{base.branch}"]]
    if args.dry_run:
        for a in plan:
            out.say(f"  (dry-run) git -C {q(w.path)} " + fmt_cmd(a, branch))
        out.data["plan"] = [f"git -C {q(w.path)} " + fmt_cmd(a, branch) for a in plan]
        return OK

    def attempt() -> subprocess.CompletedProcess:
        step(out, w.path, plan[0])
        p = step(out, w.path, plan[1], check=False, branch=branch)
        if p.returncode != 0:
            files = conflicted(w.path)
            git(w.path, "merge", "--abort", check=False)
            step(out, w.path, ["switch", branch], branch=branch)
            if files:
                raise WtError(f"base 와 병합 충돌 {len(files)}개 — sync 로 base 를 반영하고 다시 검증한 뒤 finish 한다",
                              CONFLICT, [f"충돌: {f}" for f in files])
            raise WtError("merge 실패", ERROR, _tail(p))
        return step(out, w.path, plan[2], check=False, timeout=180)

    p = attempt()
    retried = False
    if p.returncode != 0 and push_rejection(p) == "protected":
        step(out, w.path, ["switch", branch], check=False, branch=branch)
        refuse(f"원격이 {base.branch} 로의 직접 push 를 거부했다 (브랜치 보호) — pr 모드로 다시", _tail(p, 4))
    if p.returncode != 0 and push_rejection(p) == "race":
        out.warn("push 가 거절됐다 (원격 base 가 그사이 움직였다) — fetch 후 한 번만 다시 한다")
        retried = True
        fetch(w.path, out)
        p = attempt()
        if p.returncode == 0:
            out.warn("다시 만든 병합은 새 원격 커밋을 포함한다 — 그 조합은 로컬에서 검증되지 않았다 (필요하면 base 에서 다시 검증)")
    if p.returncode != 0:
        step(out, w.path, ["switch", branch], check=False, branch=branch)
        raise WtError("push 실패" + (" (재시도 후)" if retried else ""), ERROR, _tail(p))
    merge_sha = gout(w.path, "rev-parse", "HEAD")
    st = dict(w.state or {})
    st["finish"] = {"mode": "push", "at": now_iso(), "merge_commit": merge_sha, "base": ref, "retried": retried}
    save_state(w, st)
    out.say(f"결과       {ref} = {merge_sha[:10]} (merge --no-ff, 첫 부모 = 이전 {base.branch})")
    out.say(f"worktree   {ref} 위 detached. 브랜치 {qb(branch)} 는 remove 때 지운다")
    _main_followup(repo, base, out)
    out.say(f"다음       python {q(SELF)} remove {st.get('slug') or q(w.path)} --delete-branch")
    out.data.update({"merge_commit": merge_sha, "retried": retried})
    return OK


def finish_pr(repo: Repo, w: WT, branch: str, base: Base, args, out: Out) -> int:
    if not base.remote:
        refuse("origin 이 없다 — pr 모드를 쓸 수 없다")
    sig = collect_signals(repo, base, full=False)
    gh_repo = sig.get("github")
    if not gh_repo:
        refuse("origin 이 GitHub 이 아니다 — pr 모드를 쓸 수 없다 (push 모드 또는 저장소 절차)")
    default_title = gout(w.path, "log", "-1", "--format=%s", "HEAD")
    push_args = ["push", "-u", base.remote, branch]
    pr_cmd = build_pr_create_cmd(gh_repo, base.branch, branch, args.title, args.body_file, default_title)
    shown_pr = fmt_cmd(pr_cmd, branch)
    out.data["plan"] = [f"git -C {q(w.path)} " + fmt_cmd(push_args, branch), shown_pr]
    if args.dry_run:
        out.say(f"  (dry-run) git -C {q(w.path)} " + fmt_cmd(push_args, branch))
        out.say(f"  (dry-run) {shown_pr}")
        if not sig.get("gh_usable"):
            out.warn("gh 를 쓸 수 없다 — 실제 실행 전에 gh 설치·로그인(gh auth login)이 필요하다")
        return OK
    if not sig.get("gh_usable"):
        refuse("gh 가 없거나 꺼져 있다 — gh 설치·로그인(gh auth login) 후 다시")
    existing = gh_pr_view(gh_repo, branch)
    p = step(out, w.path, push_args, check=False, timeout=180, branch=branch)
    if p.returncode != 0:
        raise WtError("push 실패", ERROR, _tail(p))
    if existing and existing.get("state") == "OPEN":
        url = existing.get("url")
        out.say(f"이미 열린 PR 이 있다 — 새로 만들지 않았다 (push 로 갱신됨): {url}")
    else:
        out.say("  $ " + shown_pr)
        pr = gh(*pr_cmd[1:], timeout=120)
        if not pr or pr.returncode != 0:
            raise WtError("gh pr create 실패", ERROR, _tail(pr) if pr else ["gh 실행 불가"])
        url = (pr.stdout.strip().splitlines() or [""])[-1]
    st = dict(w.state or {})
    st["finish"] = {"mode": "pr", "at": now_iso(), "pr_url": url, "base": base.ref}
    save_state(w, st)
    out.say(f"결과       PR {url}")
    out.say("정리       PR 이 머지되면 status 에 MERGED→remove 가 뜬다 → remove --delete-branch (또는 clean)")
    _main_followup(repo, base, out)
    out.data.update({"pr_url": url})
    return OK


def finish_local(repo: Repo, w: WT, branch: str, base: Base, args, out: Out) -> int:
    lb = base.branch
    if not ref_exists(repo.git_cwd, f"refs/heads/{lb}"):
        refuse(f"로컬 base 브랜치가 없다: {lb}")
    holder = next((x for x in repo.worktrees if x.branch == lb and x.prunable is None), None)
    if holder:
        line = f"git -C {q(holder.path)} merge --no-ff --no-edit {qb(branch)}"
        out.say(f"base 브랜치 {qb(lb)} 는 {holder.path} 에 checkout 돼 있다 — 그 폴더는 건드리지 않는다")
        out.say(f"그 폴더가 한가해지면 한 줄:  {line}")
        out.say(f"브랜치 {qb(branch)} 는 남겨 둔다 (합친 뒤 status 가 MERGED→remove 를 표시한다)")
        if not args.dry_run:
            st = dict(w.state or {})
            st["finish"] = {"mode": "local", "at": now_iso(), "deferred": True, "holder": holder.path}
            save_state(w, st)
        out.data.update({"deferred": True, "holder": holder.path, "one_liner": line})
        return OK
    msg = merge_message_args(branch, lb, args)
    plan = [["switch", "--detach", lb], ["merge", "--no-ff", "--no-edit", *msg, branch], ["branch", "-f", lb, "HEAD"]]
    if args.dry_run:
        for a in plan:
            out.say(f"  (dry-run) git -C {q(w.path)} " + fmt_cmd(a, branch))
        out.data["plan"] = [f"git -C {q(w.path)} " + fmt_cmd(a, branch) for a in plan]
        return OK
    old = rev(repo.git_cwd, f"refs/heads/{lb}")
    step(out, w.path, plan[0])
    p = step(out, w.path, plan[1], check=False, branch=branch)
    if p.returncode != 0:
        files = conflicted(w.path)
        git(w.path, "merge", "--abort", check=False)
        step(out, w.path, ["switch", branch], branch=branch)
        raise WtError("병합 실패 — sync 후 다시", CONFLICT if files else ERROR, [f"충돌: {f}" for f in files] or _tail(p))
    new = gout(w.path, "rev-parse", "HEAD")
    if rev(repo.git_cwd, f"refs/heads/{lb}") != old:
        step(out, w.path, ["switch", branch], branch=branch)
        refuse(f"{lb} 가 그사이 움직였다 — sync 후 다시")
    p = step(out, w.path, ["branch", "-f", lb, new], check=False)  # 다른 worktree 가 checkout 했으면 git 이 거부한다
    if p.returncode != 0:
        step(out, w.path, ["switch", branch], check=False, branch=branch)
        raise WtError(f"{lb} 를 옮기지 못했다", ERROR, _tail(p))
    st = dict(w.state or {})
    st["finish"] = {"mode": "local", "at": now_iso(), "merge_commit": new, "base": lb}
    save_state(w, st)
    out.say(f"결과       로컬 {lb} = {new[:10]} (merge --no-ff)" + (" — 원격에는 올리지 않았다" if repo.remote else ""))
    out.say(f"worktree   {lb} 위 detached. 다음: python {q(SELF)} remove {st.get('slug') or q(w.path)} --delete-branch")
    out.data.update({"merge_commit": new})
    return OK


# ---------------------------------------------------------------- remove / clean

def backup_includes(repo: Repo, w: WT, slug: str, out: Out) -> tuple[str | None, list[str]]:
    """worktree remove 는 ignored 파일을 경고 없이 지운다. 메인에서 복사한 뒤 바뀐 것과 새로 생긴 설정을 백업한다."""
    st = w.state or {}
    recorded = {c["path"]: c.get("sha256") for c in st.get("copied", []) if isinstance(c, dict) and c.get("path")}
    roots = [x for x in (repo.main.path, w.path) if os.path.isdir(x)]
    patterns, _ = include_patterns(*roots)
    current, _ = find_include_files(w.path, patterns)
    todo = []
    for rel in sorted(set(current) | set(recorded)):
        f = join_rel(w.path, rel)
        if not os.path.isfile(f) or is_link(f):
            continue
        if rel in recorded and recorded[rel] == sha256_file(f):
            continue
        todo.append(rel)
    if not todo:
        return None, []
    dest = os.path.join(repo.wt_root, ".backup", f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}")
    for rel in todo:
        d = join_rel(dest, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(join_rel(w.path, rel), d)
    out.say(f"백업       {', '.join(todo)} → {dest}")
    return dest, todo


def delete_branch(repo: Repo, branch: str, base: Base, bi: dict, out: Out) -> str:
    """머지된 브랜치만 지운다. -d 가 base 기준으로 판단하도록 upstream 이 없으면 잠시 base 로 잡는다."""
    cwd, full = repo.git_cwd, f"refs/heads/{branch}"
    up = gout(cwd, "for-each-ref", "--format=%(upstream)", full)
    up_ok = bool(up) and ref_exists(cwd, up)
    if not up_ok and base.ref:
        git(cwd, "branch", f"--set-upstream-to={base.ref}", branch, check=False)
    p = step(out, cwd, ["branch", "-d", branch], check=False, branch=branch)
    if p.returncode == 0:
        return "삭제 (-d)"
    pr = bi.get("pr") or {}
    if bi.get("merged_via") == "pr" and pr.get("state") == "MERGED":
        p = step(out, cwd, ["branch", "-D", branch], check=False, branch=branch)
        if p.returncode == 0:
            return f"삭제 (-D: PR #{pr.get('number')} MERGED — squash 머지라 -d 가 알아보지 못함)"
    if not up_ok:
        git(cwd, "branch", "--unset-upstream", branch, check=False)
    return f"남김 (-d 거부: {' '.join(_tail(p, 1))}) — 확인 후 직접: git branch -D {qb(branch)}"


def remove_one(repo: Repo, w: WT, *, delete: bool, force: bool, out: Out, sig: dict | None = None) -> dict:
    st = w.state or {}
    slug = st.get("slug") or os.path.basename(w.path.rstrip("\\/"))
    present = w.present
    if w.is_main:
        refuse("메인 worktree 는 지우지 않는다")
    if present and inside(os.getcwd(), w.path):
        refuse("지금 작업 폴더(cwd)가 이 worktree 안이다 — ExitWorktree(action: \"keep\") 로 나오거나 메인 폴더에서 다시 실행한다",
               ["세션을 이 폴더에서 시작했다면 지울 수 없다(Windows 는 실행 중인 프로세스의 cwd 를 못 지운다) — 나중에 메인 폴더에서 remove 나 clean"])
    if w.locked is not None:
        refuse(f"잠긴 worktree 다 (이유: {w.locked or '없음'}) — 확인 후 git worktree unlock {q(w.path)}")
    branch = w.branch or st.get("branch")
    if present:
        op = op_in_progress(w.path)
        if op:
            refuse(f"{op} 이(가) 진행 중이다 — 끝내거나 abort 한 뒤 다시 (지우지 않았다)")
        dirty = dirty_lines(w.path)
        if dirty:
            refuse(f"커밋 안 된 변경 {len(dirty)}개 — 커밋하거나 버린 뒤 다시 (지우지 않았다)", dirty[:20])
    base = base_for(repo, w)
    sig = sig if sig is not None else collect_signals(repo, base, full=False)
    bi = branch_info(repo, branch, base, st, sig)
    if bi["exists"] and bi["unsafe"] and not bi["merged"] and not force:
        refuse(f"브랜치 {qb(branch)} 에 원격에도 base 에도 없는 커밋 {bi['unsafe']}개가 있다 — 먼저 finish 한다",
               ["사용자가 명시적으로 확인했을 때만 --force (폴더만 지우고 브랜치는 남긴다)"])
    out.say(f"remove: {w.path}")
    for port in busy_ports(st):
        out.warn(f"포트 {port} 에서 무언가 LISTEN 중이다 — 이 worktree 의 서버라면 먼저 끈다 (파일 잠금)")
    backup, backed = (None, [])
    links = 0
    if present:
        backup, backed = backup_includes(repo, w, slug, out)
        links = unlink_links(w.path, out, keep=tracked_links(w.path))
        if links:
            out.say(f"링크       junction·symlink {links}개를 먼저 해제했다 (대상은 그대로)")
    p = step(out, repo.git_cwd, ["worktree", "remove", w.path], check=False, timeout=1800)
    if p.returncode != 0:
        raise WtError("git worktree remove 실패", ERROR, _tail(p) + [
            "파일 잠금이면 그 폴더를 쓰는 프로세스(dev 서버·터미널·에디터·Claude 세션)를 끈 뒤 remove 를 다시 실행한다",
            f"일부만 지워져 dirty 로 보이면 사용자 확인 후: git worktree remove --force {q(w.path)}"])
    leftover = os.path.lexists(w.path)
    if leftover:
        out.warn(f"폴더가 남았다: {w.path} — 파일을 잡고 있는 프로세스(이 폴더에서 띄운 Claude·dev 서버·터미널)를 끈 뒤 지운다")
    result_branch = None
    if bi["exists"]:
        if delete and (bi["merged"] or bi["commits"] == 0):
            result_branch = delete_branch(repo, branch, base, bi, out)
        elif delete:
            result_branch = f"남김 (머지 안 됨) — 커밋 {bi['tip'][:10]}"
            if (bi.get("pr") or {}).get("state") == "OPEN":
                result_branch += f", PR #{bi['pr'].get('number')} 이 아직 열려 있다"
        else:
            result_branch = "남김"
        if repo.remote and ref_exists(repo.git_cwd, f"refs/remotes/{repo.remote}/{branch}") and bi["merged"]:
            out.say(f"참고       원격 브랜치도 지우려면: git push {repo.remote} --delete {qb(branch)}")
    step(out, repo.git_cwd, ["worktree", "prune"], check=False)
    root_gone = remove_empty_root(repo)
    out.say(f"결과       {'폴더 남음' if leftover else '지움'} · 브랜치 {qb(branch or '-')}: {result_branch or '없음'}"
            + (f" · {repo.wt_root} 비어서 지움" if root_gone else ""))
    return {"path": w.path, "slug": slug, "removed": not leftover, "leftover": leftover, "branch": branch,
            "branch_result": result_branch, "backup": backup, "backed_up": backed, "links_unlinked": links,
            "code": LEFTOVER if leftover else OK}


def cmd_remove(repo: Repo, args, out: Out) -> int:
    w = resolve_target(repo, args.target, need_present=False)
    res = remove_one(repo, w, delete=args.delete_branch, force=args.force, out=out)
    out.data.update({"command": "remove", **res})
    return res["code"]


def cmd_clean(repo: Repo, args, out: Out) -> int:
    base = default_base(repo, soft=True)
    sig = collect_signals(repo, base, full=False)
    targets, skipped = [], []
    for w in repo.linked:
        if not w.managed:
            continue
        row = analyze(repo, w, sig)
        if not row["merged"]:
            continue
        why = "DIRTY" if row["dirty"] else "현재 작업 폴더(cwd)" if row["is_cwd"] else "LOCKED" if w.locked is not None else None
        (skipped if why else targets).append((w, row, why))
    prune_preview = [ln for ln in gout(repo.git_cwd, "worktree", "prune", "--dry-run", "--verbose").splitlines() if ln.strip()]
    leftovers = find_leftovers(repo)
    zombies = [d for d in leftovers if not has_regular_files(d)]
    out.say(f"make-worktree clean — {repo.name}" + ("" if args.yes else " (dry-run: 아무것도 지우지 않는다)"))
    for w, row, _ in targets:
        out.say(f"  지울 것   [{row['slug']}] {qb(row['branch'] or '-')} (머지됨: {row['merged_via']}) {w.path}")
    for w, row, why in skipped:
        out.say(f"  건너뜀   [{row['slug']}] {why} — {w.path}")
    for ln in prune_preview:
        out.say(f"  prune    {ln}")
    for d in leftovers:
        out.say(f"  LEFTOVER {d}" + (" (빈 껍데기 — 지운다)" if d in zombies else " (파일이 있어 직접 확인)"))
    data = {"command": "clean", "dry_run": not args.yes, "targets": [r for _, r, _ in targets],
            "skipped": [{"path": w.path, "reason": why} for w, _, why in skipped],
            "prune": prune_preview, "leftovers": leftovers}
    if not args.yes:
        if targets or prune_preview or zombies:
            out.say(f"사용자에게 위 목록을 확인받은 뒤: python {q(SELF)} clean --yes")
        else:
            out.say("정리할 것이 없다")
        out.data.update(data)
        return OK
    worst, results = OK, []
    for w, row, _ in targets:
        try:
            res = remove_one(repo, w, delete=True, force=False, out=out, sig=sig)
        except WtError as e:
            res = {"path": w.path, "error": str(e), "details": e.details, "code": e.code}
            out.say(f"  실패: {w.path} — {e}")
        results.append(res)
        worst = max(worst, res["code"])
    if prune_preview:
        step(out, repo.git_cwd, ["worktree", "prune", "--verbose"], check=False)
    for d in zombies:
        unlink_links(d, out)
        shutil.rmtree(d, ignore_errors=True)
        if os.path.lexists(d):
            out.warn(f"빈 껍데기 폴더를 지우지 못했다: {d}")
            worst = max(worst, LEFTOVER)
        else:
            out.say(f"  지움     빈 껍데기 {d}")
    remove_empty_root(repo)
    data["results"] = results
    out.data.update(data)
    return worst


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="저장소 안의 아무 폴더 (기본: 현재 폴더)")
    common.add_argument("--json", action="store_true", help="결과를 JSON 하나로 stdout 에 (진행 메시지는 stderr)")
    p = argparse.ArgumentParser(prog="wt.py", description="git worktree 로 작업별 일회용 폴더(<repo>.wt/<slug>)를 다룬다.",
                                epilog="종료 코드: 0 성공 · 1 오류 · 2 거부 · 3 충돌 · 4 정리 미완")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("new", parents=[common], help="새 worktree 를 만든다")
    s.add_argument("slug", help="영어 kebab-case, 30자 이하 (예: login-fix)")
    s.add_argument("--branch", help="브랜치 이름 (기본: wt/<slug>)")
    s.add_argument("--base", help="시작점·통합 대상 (기본: origin/HEAD, 원격이 없으면 메인 HEAD)")
    s.add_argument("--from-head", action="store_true", help="메인 worktree 의 HEAD 커밋에서 시작 (미커밋 변경은 안 따라온다)")
    s.add_argument("--no-fetch", action="store_true", help="fetch 를 건너뛴다")
    s.add_argument("--no-copy", action="store_true", help="ignored 로컬 설정(.env 등)을 복사하지 않는다")
    s.add_argument("--install", action="store_true", help="lockfile 로 감지한 설치 명령을 실행한다")

    s = sub.add_parser("status", parents=[common], help="worktree 상태와 finish 방식 추천")
    s.add_argument("--all", action="store_true", help="메인과 관리 밖 worktree 도 보여 준다")
    s.add_argument("--fetch", action="store_true", help="먼저 origin 을 fetch 한다")

    s = sub.add_parser("sync", parents=[common], help="worktree 안에서 base 를 병합한다")
    s.add_argument("target", nargs="?", help="slug 또는 경로 (기본: 현재 폴더)")
    s.add_argument("--rebase", action="store_true", help="merge 대신 rebase (push 안 한 브랜치만)")
    s.add_argument("--no-fetch", action="store_true")
    s.add_argument("--base", help="base 브랜치를 바꾼다 (기본: 만들 때 정한 것)")

    s = sub.add_parser("finish", parents=[common], help="합친다 (--mode 없으면 점검과 추천만)")
    s.add_argument("target", nargs="?", help="slug 또는 경로 (기본: 현재 폴더)")
    s.add_argument("--mode", choices=("pr", "push", "local"))
    s.add_argument("--title", help="PR 제목 또는 merge 커밋 제목")
    s.add_argument("--body-file", help="PR 본문 또는 merge 커밋 본문 파일")
    s.add_argument("--dry-run", action="store_true", help="실행할 명령만 보여 준다")
    s.add_argument("--no-fetch", action="store_true")
    s.add_argument("--base", help="base 브랜치를 바꾼다")

    s = sub.add_parser("remove", parents=[common], help="worktree 를 지운다")
    s.add_argument("target", help="slug 또는 경로")
    s.add_argument("--delete-branch", action="store_true", help="머지된 브랜치도 지운다")
    s.add_argument("--force", action="store_true", help="push·merge 안 된 커밋이 있어도 폴더를 지운다 (브랜치는 남김). 사용자 확인 필수")

    s = sub.add_parser("clean", parents=[common], help="머지된 worktree 를 정리한다 (기본 dry-run)")
    s.add_argument("--yes", action="store_true", help="실제로 지운다")
    return p


COMMANDS = {"new": cmd_new, "status": cmd_status, "sync": cmd_sync, "finish": cmd_finish,
            "remove": cmd_remove, "clean": cmd_clean}


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    out = Out(args.json)
    try:
        start = args.repo
        target = getattr(args, "target", None)
        if not start and target and not SLUG_RE.match(target) and os.path.isdir(display(target)):
            start = target  # 다른 저장소의 worktree 경로를 준 경우
        repo = load_repo(start or os.getcwd())
        code = COMMANDS[args.command](repo, args, out)
    except WtError as e:
        code = e.code
        out.data.update({"error": str(e), "details": e.details})
        label = {REFUSED: "거부", CONFLICT: "충돌"}.get(e.code, "오류")
        print(f"{label}: {e}", file=sys.stderr)
        for d in e.details:
            print(f"  {d}", file=sys.stderr)
    except KeyboardInterrupt:
        code = 130
    if args.json:
        out.data.setdefault("command", args.command)
        out.data.update({"ok": code == OK, "code": code, "warnings": out.warnings})
        print(json.dumps(out.data, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
