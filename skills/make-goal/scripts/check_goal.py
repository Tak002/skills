#!/usr/bin/env python
"""goal 검사기 — Claude Code `/goal` 조건문과 Codex goal objective 의 길이·형식을 검사한다.

사용법:
  python check_goal.py <파일|-> [--target claude|codex] [--limit 4000] [--shell bash|powershell] [--json]

  <파일|->   검사할 goal 텍스트. `-` 면 표준 입력. UTF-8 (BOM 허용).
  --target   claude(기본) | codex. 세는 방식과 필수 섹션이 다르다.
  --limit    하드 제한 (기본 4000). OpenChamber 는 5000.
  --shell    bash(기본) | powershell. exit code 관용구 검사에 쓴다.
  --json     사람용 출력 대신 JSON 한 개.

길이는 맨 앞의 `/goal` 토큰을 떼고 앞뒤 공백을 자른 뒤 센다 (줄바꿈은 LF 로 맞춘다).
  claude  UTF-16 code unit 수 = JS String.length       (한글 1, 이모지 2)
  codex   Unicode scalar 수   = Rust chars().count()    (한글 1, 이모지 1)

종료 코드: 0 통과 (경고만 있어도 0), 1 오류 있음, 2 사용법·입력 오류.
규칙 표는 ../reference.md 8절. 표준 라이브러리만 쓴다 (Python 3.10+).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_LIMIT = 4000
SOFT_LIMIT = 3500
FRONT_WINDOW = 500
C_MIN, C_MAX = 3, 7
TARGETS = ("claude", "codex")
SHELLS = ("bash", "powershell")

# JS String.prototype.trim 이 지우는 문자 (WhiteSpace + LineTerminator)
_ZS = "".join(chr(c) for c in range(0x2000, 0x200B))
JS_WHITESPACE = "\t\n\v\f\r   " + _ZS + "    　﻿"
# Rust str::trim 이 지우는 문자 (Unicode White_Space)
RUST_WHITESPACE = "\t\n\v\f\r \u0085  " + _ZS + "    　"

GOAL_PREFIX_RE = re.compile(r"/goal(?![\w-])")

# ---------- 섹션 ----------
# 머리 이름은 공백·구분 기호를 지운 뒤 비교한다: [막힘·중단] [막힘 / 중단] [막힘ㆍ중단] [막힘] 은 모두 같은 섹션.
SECTION_ALIASES = {
    "목표": "목표", "goal": "목표", "objective": "목표",
    "완료조건": "완료 조건", "완료기준": "완료 조건", "완료": "완료 조건", "acceptance": "완료 조건",
    "증거규칙": "증거 규칙", "증거": "증거 규칙", "evidence": "증거 규칙",
    "제약": "제약", "제약조건": "제약", "가드레일": "제약", "금지": "제약", "constraints": "제약",
    "범위밖": "범위 밖", "범위외": "범위 밖", "비범위": "범위 밖", "outofscope": "범위 밖",
    "막힘중단": "막힘·중단", "막힘": "막힘·중단", "중단": "막힘·중단", "blocked": "막힘·중단",
    "참고": "참고", "참고판정대상아님": "참고", "notes": "참고",
    "보고": "보고", "완료보고": "보고", "report": "보고",
}
REQUIRED = {
    "claude": ("목표", "완료 조건", "증거 규칙", "제약", "막힘·중단"),
    "codex": ("목표", "완료 조건", "제약", "막힘·중단"),
}
HEADER_RE = re.compile(r"\[([^\[\]\n]{1,24})\]")
HEADER_SEP_RE = re.compile(r"[\s·ㆍ・•/,&+_()\-]")

# ---------- C 항목 ----------
C_LINE_RE = re.compile(r"^[ \t>]*(?:[-*•][ \t]*)?(?:\*\*)?C(\d{1,2})(?:\*\*)?[ \t]*[.)．:：]", re.M)
C_INLINE_RE = re.compile(r"(?<=[ \t])C(\d{1,2})[.．:：](?=[ \t])")
CHECK_WORD_RE = re.compile(r"확인|\b(?:check|verify)\b\s*[:：]", re.I)
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
EXPECT_RE = re.compile(
    r"→|->|=>|EXIT\s*=|\bexit(?:s|\s+code)?\s*0\b|종료\s*코드\s*0"
    r"|≥|≤|>=|<=|==|=\s*\d"
    r"|\d+\s*(?:건|개|행|줄|%)"
    r"|이상|이하|미만|초과|이내"
    r"|\b(?:passed|failed|pass|fail|success(?:ful)?|ok|green|clean)\b"
    r"|비어\s*있|빈\s*출력|출력(?:이)?\s*없|없음"
    r"|(?:으)?로\s*시작|포함|일치|같다|동일",
    re.I,
)
KNOWN_COMMANDS = {
    # JS/TS
    "pnpm", "npm", "npx", "yarn", "bun", "bunx", "node", "deno", "tsx", "ts-node", "tsc", "eslint", "prettier",
    "vitest", "jest", "mocha", "playwright", "cypress", "biome", "turbo", "nx", "lerna",
    # Python
    "python", "python3", "py", "pip", "uv", "uvx", "poetry", "pytest", "tox", "nox", "mypy", "ruff", "black",
    "flake8", "pylint", "pyright", "coverage", "alembic",
    # JVM / 기타 언어
    "gradle", "gradlew", "mvn", "mvnw", "java", "javac", "kotlin", "sbt", "go", "cargo", "rustc", "dotnet",
    "ruby", "bundle", "rake", "rspec", "rails", "php", "composer", "phpunit", "swift", "xcodebuild",
    "flutter", "dart", "mix", "elixir", "clang", "gcc", "g++", "make", "cmake", "ctest", "bazel",
    # 셸·유틸
    "git", "gh", "grep", "rg", "egrep", "fgrep", "ag", "wc", "sed", "awk", "head", "tail", "cat", "ls", "find",
    "diff", "cmp", "sort", "uniq", "cut", "tr", "xargs", "jq", "yq", "curl", "wget", "echo", "test", "printf",
    "stat", "du", "bash", "sh", "zsh", "pwsh", "powershell", "docker", "docker-compose", "kubectl", "helm",
    "terraform", "psql", "mysql", "sqlite3", "redis-cli", "shellcheck", "hadolint", "markdownlint", "lychee",
    "pre-commit", "sqlfluff",
    # PowerShell
    "get-childitem", "select-string", "measure-object", "get-content", "test-path", "invoke-webrequest",
    "invoke-pester", "select-object", "where-object", "findstr",
}
SHELL_OP_RE = re.compile(r"\|\s*[\w$]|&&|\|\||;\s*\S|2>&1|\s>>?\s")
FILE_REF_RE = re.compile(
    r"(?:[A-Za-z0-9_.\-]+[/\\])+[A-Za-z0-9_.\-*]+"
    r"|\b[\w\-]+\.(?:md|markdown|txt|json|jsonl|ya?ml|toml|csv|tsv|html?|xml|ini|cfg|conf|lock|log|py|ts|tsx|js"
    r"|jsx|mjs|cjs|java|kt|kts|go|rs|rb|php|cs|sql|sh|ps1|ipynb|pdf|docx|xlsx)\b"
    r"|명세대로|스펙대로|계획대로|문서대로|파일대로|명세(?:서)?에\s*따라",
    re.I,
)

# ---------- 표현 ----------
SUBJECTIVE_RE = re.compile(
    r"깔끔|적절|충분|최적|완벽|개선|가능한\s*한|최대한|읽기\s*좋|유지\s*보수(?:하기|가)?\s*(?:좋|쉽)|보기\s*좋"
    r"|견고|효율적|자연스럽|매끄럽|알아서|제대로"
    r"|(?<![가-힣])잘(?=\s|된|되|하게|해|$)"
    r"|production[- ]?ready|\bproperly\b|\brobust\b|\boptimal\b|\bperfect(?:ly)?\b|as much as possible"
    r"|best practices?|clean code|\belegant\b",
    re.I,
)
TURN_CAP_RE = re.compile(
    r"GOAL-TURN|GOAL-STATUS\s*:?\s*STOPPED"
    r"|\d+\s*턴\s*(?:을|를|이|가)?\s*(?:넘기면|넘으면|넘어가면|초과|후|뒤|지나면|안에|이내|까지|째)"
    r"|턴\s*상한|최대\s*\d+\s*턴"
    r"|(?:stop|halt|give up)\s+after\s+\d+\s+turns?|\bmax(?:imum)?\s+(?:of\s+)?\d+\s+turns?",
    re.I,
)
TEMPLATE_TOKEN_RE = re.compile(r"(?<!\$)\{([^{}\n]{1,80})\}")
TEMPLATE_LINE_RE = re.compile(r"^[ \t]*(?:…|\.\.\.)[ \t]*(?:\(.*\))?[ \t]*$", re.M)
HANGUL_RE = re.compile(r"[가-힣]")
PROHIBIT_RE = re.compile(r"금지|하지\s*않|않는다|말\s*것|말고|\bnever\b|\bdo not\b|\bdon't\b|\bmust not\b", re.I)
GIT_CHECK_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:diff|status|ls-files)\b")
RERUN_RE = re.compile(r"다시\s*실행|재실행|다시\s*돌|re-?run", re.I)


# ---------- 자료 구조 ----------
@dataclass
class Issue:
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


@dataclass
class Section:
    name: str      # 정규화한 이름 (예: "막힘·중단")
    start: int     # 머리 '[' 위치 (정규화한 텍스트 기준 code point)
    body: str      # 머리 뒤부터 다음 섹션 머리 전까지


@dataclass
class CItem:
    number: int
    text: str


@dataclass
class Result:
    target: str
    limit: int
    soft_limit: int
    length: int
    sections: list[tuple[str, int]]
    c_numbers: list[int]
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "target": self.target,
            "unit": "utf16" if self.target == "claude" else "codepoint",
            "length": self.length,
            "limit": self.limit,
            "soft_limit": self.soft_limit,
            "over": max(0, self.length - self.limit),
            "sections": [{"name": n, "length": ln} for n, ln in self.sections],
            "c_items": self.c_numbers,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "notes": self.notes,
        }


# ---------- 길이 ----------
def strip_fence(text: str) -> tuple[str, bool]:
    """전체가 ``` 코드 블록으로 감싸여 있으면 울타리 줄을 뗀다."""
    lines = text.strip().split("\n")
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]), True
    return text, False


def normalize(raw: str, target: str = "claude") -> str:
    """줄바꿈을 LF 로 맞추고, 앞뒤 공백 → 맨 앞 `/goal` 토큰 → 다시 앞뒤 공백 순으로 뗀다.
    공백 집합은 제품이 쓰는 trim 과 같다 (claude=JS trim, codex=Rust trim)."""
    ws = JS_WHITESPACE if target == "claude" else RUST_WHITESPACE
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip(ws)
    m = GOAL_PREFIX_RE.match(text)
    if m:
        text = text[m.end():].strip(ws)
    return text


def units(s: str, target: str = "claude") -> int:
    """claude: UTF-16 code unit 수 (JS length). codex: code point 수 (Rust chars().count())."""
    if target == "claude":
        return len(s.encode("utf-16-le", "surrogatepass")) // 2
    return len(s)


def count_length(raw: str, target: str = "claude") -> int:
    return units(normalize(raw, target), target)


# ---------- 파싱 ----------
def section_key(inner: str) -> str | None:
    return SECTION_ALIASES.get(HEADER_SEP_RE.sub("", inner).lower())


def parse_sections(text: str) -> tuple[list[Section], str]:
    """알려진 [머리] 로 섹션을 나눈다. 같은 이름이 여러 번 나오면 줄 맨 앞의 첫 번째를 머리로 보고
    나머지는 본문 속 언급으로 둔다. 돌려주는 값: (섹션 목록, 첫 머리 앞의 글)."""
    found: dict[str, list[tuple[int, int, bool]]] = {}
    for m in HEADER_RE.finditer(text):
        name = section_key(m.group(1))
        if not name:
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        at_line_start = re.fullmatch(r"[\s>*#\-•]*", text[line_start:m.start()]) is not None
        found.setdefault(name, []).append((m.start(), m.end(), at_line_start))
    chosen = []
    for name, occ in found.items():
        start, end, _ = next((o for o in occ if o[2]), occ[0])
        chosen.append((start, end, name))
    chosen.sort()
    sections = []
    for i, (start, end, name) in enumerate(chosen):
        nxt = chosen[i + 1][0] if i + 1 < len(chosen) else len(text)
        sections.append(Section(name, start, text[end:nxt]))
    preamble = text[: chosen[0][0]] if chosen else text
    return sections, preamble


def parse_c_items(body: str) -> list[CItem]:
    """C1. C2) **C3.** - C4: 처럼 줄 맨 앞에 있거나, 공백 뒤 `C5. ` 처럼 이어 쓴 항목을 찾는다."""
    starts: dict[int, int] = {}
    for rx in (C_LINE_RE, C_INLINE_RE):
        for m in rx.finditer(body):
            starts.setdefault(m.start(1) - 1, int(m.group(1)))
    pos = sorted(starts)
    items = []
    for i, p in enumerate(pos):
        end = pos[i + 1] if i + 1 < len(pos) else len(body)
        items.append(CItem(starts[p], body[p:end].strip()))
    return items


def is_command(span: str) -> bool:
    """백틱 안의 글이 실행할 명령처럼 보이는지. 파일 경로·식별자·기대값(`EXIT=0`, `1 passed`)은 아니다."""
    s = span.strip()
    if s.startswith("$ "):
        s = s[2:].lstrip()
    parts = s.split()
    if not parts:
        return False
    first = parts[0]
    if first.lower() in KNOWN_COMMANDS or Path(first).name.lower() in KNOWN_COMMANDS:
        return True
    if first.startswith(("./", ".\\", "../", "..\\", "~/")) and len(first) > 2:
        return True
    return bool(SHELL_OP_RE.search(s)) and len(parts) > 1


def commands_in(text: str) -> list[str]:
    return [m.group(1) for m in BACKTICK_RE.finditer(text) if is_command(m.group(1))]


# ---------- 검사 ----------
def check(raw: str, target: str = "claude", limit: int = DEFAULT_LIMIT, shell: str = "bash") -> Result:
    if target not in TARGETS:
        raise ValueError(f"target 은 {TARGETS} 중 하나다: {target}")
    if shell not in SHELLS:
        raise ValueError(f"shell 은 {SHELLS} 중 하나다: {shell}")
    unfenced, fenced = strip_fence(raw.replace("\r\n", "\n").replace("\r", "\n"))
    text = normalize(unfenced, target)
    n = units(text, target)
    soft = min(SOFT_LIMIT, int(limit * 0.875))
    sections, preamble = parse_sections(text)
    by_name = {s.name: s for s in sections}
    sec_lengths = []
    for i, s in enumerate(sections):
        end = sections[i + 1].start if i + 1 < len(sections) else len(text)
        sec_lengths.append((s.name, units(text[s.start:end], target)))
    body = by_name["완료 조건"].body if "완료 조건" in by_name else text
    items = parse_c_items(body)
    res = Result(target, limit, soft, n, sec_lengths, [c.number for c in items])
    err = lambda code, msg: res.errors.append(Issue(code, msg))  # noqa: E731
    warn = lambda code, msg: res.warnings.append(Issue(code, msg))  # noqa: E731

    if fenced:
        res.notes.append("코드 블록 울타리(```)를 떼고 셌다.")
    if limit > DEFAULT_LIMIT:
        res.notes.append(f"--limit {limit:,}: Claude Code·Codex 의 실제 제한은 4,000자다 (5,000 은 OpenChamber 의 제한).")
    if not text:
        err("empty", "goal 이 비어 있다.")
        return res

    # --- 오류 ---
    if n > limit:
        err("length", f"길이 {n:,}자가 제한 {limit:,}자를 {n - limit:,}자 넘는다. 압축 사다리를 적용하거나 런처 + 명세로 나눈다.")
    for name in REQUIRED[target]:
        if name not in by_name:
            err("section-missing", f"필수 섹션 [{name}] 이 없다.")
    if not items:
        err("no-c-items", "완료 조건 항목(C1, C2, …)이 없다. 줄 맨 앞에 `C1. 상태 — 확인: `명령` → 기대값` 으로 쓴다.")
    for c in items:
        if not CHECK_WORD_RE.search(c.text):
            err("c-no-check", f"C{c.number} 에 '확인' 이 없다. '상태 — 확인: `명령` → 기대값' 으로 쓴다.")
    tokens = []
    for m in TEMPLATE_TOKEN_RE.finditer(text):
        inner = m.group(1).strip()
        if inner[:1] in "\"'":
            continue
        if HANGUL_RE.search(inner) or "…" in inner or "..." in inner or inner in ("n", "N"):
            tokens.append(m.group(0))
    tokens += [m.group(0).strip() for m in TEMPLATE_LINE_RE.finditer(text)]
    for tok in dict.fromkeys(tokens):
        err("template-token", f"채우지 않은 템플릿 자리표시 '{tok}' 가 남아 있다.")
    if target == "claude" and "GOAL-STATUS" not in text:
        err("no-goal-status", "종료 절이 없다. `GOAL-STATUS: BLOCKED — <원인>` 과 `GOAL-STATUS: STOPPED — <남은 일>` 을 넣는다.")

    # --- 경고 ---
    if soft < n <= limit:
        warn("length-soft", f"길이 {n:,}자가 권장 {soft:,}자를 넘는다. 조건문은 매 턴 다시 읽히고 판정 피드백에는 500자로 잘려 인용되므로 짧을수록 낫다.")
    for name in ("목표", "완료 조건"):
        if name in by_name:
            pos = units(text[: by_name[name].start], target)
            if pos >= FRONT_WINDOW:
                warn("front-500", f"[{name}] 이 앞 {FRONT_WINDOW}자 안에 없다 ({pos:,}자 위치). 목표와 완료 조건 머리를 맨 앞에 둔다.")
    if items and not (C_MIN <= len(items) <= C_MAX):
        warn("c-count", f"C 항목이 {len(items)}개다. 3–7개를 권장한다.")
    nums = [c.number for c in items]
    if items and nums != list(range(1, len(items) + 1)):
        warn("c-numbering", f"C 번호가 {', '.join(f'C{k}' for k in nums)} 이다. C1 부터 빠짐없이 매긴다.")
    for c in items:
        if not commands_in(c.text):
            ref = FILE_REF_RE.search(c.text)
            if target == "claude" and ref:
                warn("judge-file-only", f"C{c.number} 가 파일('{ref.group(0)}')만 가리키고 출력 명령이 없다. "
                                        "Claude 판정자는 파일을 못 읽으니 `grep`·`sed`·검사 스크립트 출력으로 확인하게 한다.")
            else:
                warn("c-no-command", f"C{c.number} 에 백틱으로 감싼 확인 명령이 없다.")
        if not EXPECT_RE.search(c.text):
            warn("c-no-expected", f"C{c.number} 에 기대값 표시(→, EXIT=0, ≥, = 0, 0건, passed 등)가 없다.")
    scope = [("머리말", preamble)] + [(s, by_name[s].body) for s in ("목표", "완료 조건") if s in by_name]
    for where, chunk in scope:
        for word in dict.fromkeys(m.group(0) for m in SUBJECTIVE_RE.finditer(chunk)):
            warn("subjective", f"[{where}] 에 판정할 수 없는 표현 '{word}' 이 있다. 측정할 수 있는 값으로 바꾼다.")
    if target == "codex":
        m = TURN_CAP_RE.search(text)
        if m:
            warn("codex-turn-cap", f"Codex goal 에 턴 상한 절('{m.group(0)}')이 있다. \"멈추는 것은 완료가 아니다\" 는 "
                                   "continuation 규칙과 충돌하므로 빼고, 예산은 goal 밖에서 token budget 으로 건다.")
        if "보고" not in by_name and "증거 규칙" not in by_name:
            warn("codex-no-report", "[보고] 가 없다. 완료 시 C 항목마다 증명 명령과 출력 한 줄을 적게 한다.")
    if target == "claude":
        if "GOAL-STATUS" in text and not re.search(r"GOAL-TURN|STOPPED", text):
            warn("no-turn-cap", "턴 상한 절이 없다. 턴마다 `GOAL-TURN k/N`, N턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>`.")
        if "증거 규칙" in by_name and not RERUN_RE.search(by_name["증거 규칙"].body):
            warn("evidence-rerun", "[증거 규칙] 에 '완료를 주장하는 턴에서 확인 명령을 다시 실행' 이 없다. "
                                   "앞 턴의 출력은 판정자 창에서 잘리거나 compaction 으로 사라진다.")
    spans = [m.group(1) for m in BACKTICK_RE.finditer(text)]
    if shell == "powershell":
        if "PIPESTATUS" in text:
            warn("shell-idiom", "PowerShell 에는 ${PIPESTATUS[0]} 가 없다. `; \"EXIT=$LASTEXITCODE\"` 를 쓴다.")
        if re.search(r"EXIT=\$\?|echo\s+\"?\$\?", text):
            warn("shell-idiom", "PowerShell 의 $? 는 True/False 다. exit code 는 $LASTEXITCODE 로 출력한다.")
    else:
        if "$LASTEXITCODE" in text:
            warn("shell-idiom", "bash 에는 $LASTEXITCODE 가 없다. `; echo \"EXIT=${PIPESTATUS[0]}\"` 를 쓴다.")
        if any("|" in s and re.search(r"\$\?", s) for s in spans):
            warn("shell-idiom", "파이프 뒤의 $? 는 마지막 명령(tail 등)의 종료 코드다. ${PIPESTATUS[0]} 를 쓴다.")
    if "제약" in by_name:
        cbody = by_name["제약"].body
        if PROHIBIT_RE.search(cbody) and not commands_in(cbody) and not GIT_CHECK_RE.search(text):
            warn("constraint-no-check", "[제약] 의 금지 조항에 확인 명령이 없다. "
                                        "`git diff --stat -- <보호 경로>` 빈 출력, `git status --porcelain` 같은 확인을 붙인다.")
    return res


# ---------- 출력 ----------
def unit_label(target: str) -> str:
    return "UTF-16 기준" if target == "claude" else "문자 수 기준"


def status_label(res: Result) -> str:
    if res.errors:
        return f"검사 실패 (오류 {len(res.errors)} · 경고 {len(res.warnings)})"
    if res.warnings:
        return f"검사 통과 (경고 {len(res.warnings)})"
    return "검사 통과"


def format_human(res: Result) -> str:
    lines = [f"길이: {res.length:,} / {res.limit:,}자 ({res.target}, {unit_label(res.target)}) · {status_label(res)}"]
    if res.sections:
        parts = [f"[{name}] {ln:,}" for name, ln in res.sections]
        lines.append("섹션: " + " · ".join(parts) + f" · C 항목 {len(res.c_numbers)}개")
    if res.errors:
        lines.append("오류:")
        lines += [f"  - [{e.code}] {e.message}" for e in res.errors]
    if res.warnings:
        lines.append("경고:")
        lines += [f"  - [{w.code}] {w.message}" for w in res.warnings]
    lines += [f"참고: {note}" for note in res.notes]
    return "\n".join(lines)


def read_input(src: str) -> str:
    """파일 또는 표준 입력을 UTF-8 로 읽는다 (BOM 제거). 실패하면 OSError / UnicodeDecodeError."""
    data = sys.stdin.buffer.read() if src == "-" else Path(src).read_bytes()
    return data.decode("utf-8-sig")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="check_goal.py",
        description="Claude Code /goal 조건문·Codex goal objective 의 길이와 형식을 검사한다.",
        epilog="종료 코드: 0 통과(경고만 있어도 0), 1 오류, 2 사용법·입력 오류.",
    )
    p.add_argument("source", help="goal 텍스트 파일 경로, 또는 표준 입력이면 -")
    p.add_argument("--target", choices=TARGETS, default="claude", help="claude(UTF-16 길이) | codex(문자 수). 기본 claude")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="하드 제한 (기본 4000, OpenChamber 는 5000)")
    p.add_argument("--shell", choices=SHELLS, default="bash", help="exit code 관용구 검사 기준 셸. 기본 bash")
    p.add_argument("--json", action="store_true", help="JSON 으로 출력")
    args = p.parse_args(argv)
    if args.limit <= 0:
        p.error("--limit 은 양의 정수여야 한다")
    return args


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    try:
        raw = read_input(args.source)
    except (OSError, UnicodeDecodeError) as e:
        print(f"check_goal: 입력을 UTF-8 로 읽지 못했다: {args.source} ({e})", file=sys.stderr)
        return 2
    res = check(raw, args.target, args.limit, args.shell)
    if args.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_human(res))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
