"""스킬 평가 실행기. 스킬을 붙였을 때와 안 붙였을 때(또는 두 버전끼리) 같은 요청을 claude CLI 로 돌리고,
응답을 다시 claude 로 채점해 합격률을 비교한다.

사용법 (저장소 루트에서):
  python workspace/run_evals.py --skill notion-export              # 전체: with-skill vs baseline 실행 + 채점 + 요약
  python workspace/run_evals.py --skill notion-export --test 2     # 2번 문제만
  python workspace/run_evals.py --skill notion-export --grade-only # 마지막 iteration 을 다시 채점만
  python workspace/run_evals.py --skill notion-export --with-skill-only
  python workspace/run_evals.py --skill notion-export --a skills/notion-export/SKILL.md --b /tmp/new/SKILL.md   # 두 버전 A/B
  python workspace/run_evals.py --skill notion-export --dry-run    # claude 를 부르지 않고 프롬프트만 출력

입력:  workspace/<skill>/evals.json  (형식은 templates/evals.json)
출력:  workspace/<skill>/iteration-N/<test-name>/<config>/outputs/response.md, timing.json, grading.txt, grading.json
       workspace/<skill>/iteration-N/summary.txt, config.json
의존성: Python 3.10+, claude CLI (PATH). 외부 패키지 없음.

기본적으로 평가 대상 claude 에는 --disallowedTools Bash,Write,Edit 를 줘서 스크립트를 실제로 실행하지 못하게 한다
(스킬이 "무엇을 하겠다" 고 답하는지를 본다). 실제 실행까지 보려면 --allow-actions.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path(__file__).resolve().parent
DEFAULT_TIMEOUT = 600
SAFE_TOOLS_ARGS = ["--disallowedTools", "Bash,Write,Edit,NotebookEdit"]

SKILL_PREFIX = (
    "Read the skill file at {path} first and follow its instructions exactly. "
    "Then handle the request below as you would for a real user.\n\nRequest: {prompt}"
)

GRADING_PROMPT = """You are grading an AI assistant's response against a list of assertions.
For EACH assertion output exactly one line, in order, in this format and nothing else:
PASS|<assertion number>|<short evidence quoted or paraphrased from the response>
FAIL|<assertion number>|<why it fails>
Do not use tools. Do not add commentary before or after the lines.

Assertions:
{assertions}

Response to grade:
<<<
{response}
>>>
"""

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ---------- 입력 ----------
def load_evals(skill: str, workspace: Path = WORKSPACE) -> dict:
    """workspace/<skill>/evals.json 을 읽고 최소 형식을 확인한다."""
    path = workspace / skill / "evals.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} 가 없다. templates/evals.json 을 복사해 만든다.")
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = validate_evals(data, skill)
    if problems:
        raise ValueError(f"{path}: " + "; ".join(problems))
    return data


def validate_evals(data: dict, skill: str | None = None) -> list[str]:
    """형식 오류 목록. 비어 있으면 정상. validate.py 도 이 함수를 쓴다."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["최상위가 객체가 아니다"]
    if skill and data.get("skill_name") != skill:
        errs.append(f"skill_name 이 '{data.get('skill_name')}' 이다 (기대: '{skill}')")
    evals = data.get("evals")
    if not isinstance(evals, list) or not evals:
        return errs + ["evals 가 비어 있거나 배열이 아니다"]
    seen_names: set[str] = set()
    for i, ev in enumerate(evals, 1):
        tag = f"evals[{i}]"
        if not isinstance(ev, dict):
            errs.append(f"{tag}: 객체가 아니다")
            continue
        for key in ("id", "name", "prompt", "assertions"):
            if key not in ev:
                errs.append(f"{tag}: '{key}' 가 없다")
        name = ev.get("name", "")
        if name and not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
            errs.append(f"{tag}: name 은 kebab-case 여야 한다 ('{name}')")
        if name in seen_names:
            errs.append(f"{tag}: name 중복 '{name}'")
        seen_names.add(name)
        a = ev.get("assertions")
        if not isinstance(a, list) or not a or not all(isinstance(x, str) and x.strip() for x in a):
            errs.append(f"{tag}: assertions 는 비어 있지 않은 문자열 배열이어야 한다")
    return errs


# ---------- iteration 폴더 ----------
def find_iteration(skill_dir: Path, grade_only: bool = False) -> Path:
    """다음 iteration 폴더 (grade_only 면 가장 최근 것)."""
    nums = sorted(int(p.name.split("-")[1]) for p in skill_dir.glob("iteration-*") if p.name.split("-")[1].isdigit())
    if grade_only:
        if not nums:
            raise FileNotFoundError(f"{skill_dir} 에 채점할 iteration 이 없다")
        return skill_dir / f"iteration-{nums[-1]}"
    return skill_dir / f"iteration-{(nums[-1] + 1) if nums else 1}"


# ---------- claude 호출 ----------
_scratch: Path | None = None


def scratch_dir() -> Path:
    """평가 대상 claude 의 작업 폴더. 저장소 밖의 빈 임시 폴더 (실행당 하나)."""
    global _scratch
    if _scratch is None:
        _scratch = Path(tempfile.mkdtemp(prefix="skill-evals-"))
    return _scratch


STAGE_IGNORE = shutil.ignore_patterns("node_modules", ".env", "__pycache__", "*.pyc", ".cache", ".pytest_cache", "iteration-*")


def config_cwd(label: str, scratch: Path | None = None) -> Path:
    """설정마다 따로 쓰는 작업 폴더. baseline 은 빈 폴더, with-skill 은 스킬 사본만 든 폴더.
    같은 폴더를 쓰면 baseline claude 가 옆에 놓인 스킬 사본을 Glob 으로 찾아 읽는다 (report-viewer 첫 격리 실행에서 10/10 vs 10/10)."""
    d = (scratch or scratch_dir()) / label
    d.mkdir(parents=True, exist_ok=True)
    return d


def stage_skill(skill_file: str, label: str, scratch: Path | None = None) -> str:
    """스킬 폴더를 그 설정의 작업 폴더 안으로 복사하고 그 안의 SKILL.md 경로를 돌려준다.

    claude -p 는 작업 폴더 밖 파일 읽기를 자동 거부하므로, 저장소의 SKILL.md 를 직접 가리키면 읽지 못한다.
    node_modules, .env(토큰) 등은 복사하지 않는다.
    """
    src = Path(skill_file).resolve()
    dst_dir = config_cwd(label, scratch) / "skills" / src.parent.name
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src.parent, dst_dir, ignore=STAGE_IGNORE)
    return str(dst_dir / src.name)


def claude_bin() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise FileNotFoundError("claude CLI 를 PATH 에서 찾지 못했다 (npm i -g @anthropic-ai/claude-code)")
    return exe


def run_claude(prompt: str, model: str | None = None, extra_args: list[str] | None = None, timeout: int = DEFAULT_TIMEOUT,
               cwd: Path | None = None) -> tuple[str, float]:
    """claude -p 로 프롬프트를 보내고 (stdout, 소요 초) 를 돌려준다.

    cwd 는 기본이 빈 임시 폴더다. 저장소 루트에서 돌리면 baseline claude 가 skills/ 를 스스로 찾아 읽어
    비교가 무의미해진다 (iteration-1 에서 실제로 그랬다).
    """
    # 프롬프트는 항상 stdin 으로. Windows 의 claude.cmd 셔틀은 argv 를 첫 줄바꿈에서 잘라 버리고,
    # --disallowedTools 같은 가변 옵션은 뒤따르는 인자를 도구 이름으로 삼킨다.
    use_stdin = True
    cmd = [claude_bin(), "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    cmd += extra_args or []
    t0 = time.time()
    proc = subprocess.run(
        cmd, input=prompt if use_stdin else None, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, cwd=str(cwd or scratch_dir()),
    )
    elapsed = time.time() - t0
    out = ANSI_RE.sub("", proc.stdout or "")
    if proc.returncode != 0 and not out.strip():
        raise RuntimeError(f"claude 종료 코드 {proc.returncode}: {(proc.stderr or '').strip()[:400]}")
    return out.strip(), elapsed


# ---------- 설정 ----------
def build_configs(args, skill: str) -> list[dict]:
    """비교할 설정 목록. 기본은 with-skill vs baseline. 스킬 경로는 절대 경로로 (claude 가 임시 폴더에서 돌기 때문)."""
    default_skill = f"skills/{skill}/SKILL.md"
    if args.a:
        configs = [{"label": args.a_label or "a", "skill": args.a}]
        if args.b:
            configs.append({"label": args.b_label or "b", "skill": args.b})
    else:
        if args.b:
            raise ValueError("--b 는 --a 와 함께 써야 한다")
        configs = [{"label": "with-skill", "skill": default_skill}]
        if not args.with_skill_only:
            configs.append({"label": "baseline", "skill": None})
    for c in configs:
        if c["skill"] and not Path(c["skill"]).is_absolute():
            c["skill"] = str((ROOT / c["skill"]).resolve())
    return configs


def make_prompt(ev: dict, config: dict, suffix: str) -> str:
    prompt = ev["prompt"]
    if suffix:
        prompt = f"{prompt}\n\n{suffix}"
    if config.get("skill"):
        return SKILL_PREFIX.format(path=config["skill"], prompt=prompt)
    return prompt


# ---------- 실행 ----------
def run_test(ev: dict, configs: list[dict], it_dir: Path, *, suffix: str = "", model: str | None = None,
             extra_args: list[str] | None = None, timeout: int = DEFAULT_TIMEOUT, dry_run: bool = False,
             runner=run_claude) -> None:
    for config in configs:
        out_dir = it_dir / ev["name"] / config["label"] / "outputs"
        prompt = make_prompt(ev, config, suffix)
        if dry_run:
            print(f"\n--- [{ev['name']}] {config['label']} ---\n{prompt}\n")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"  [{ev['name']}] {config['label']} ... ", end="", flush=True)
        try:
            response, elapsed = runner(prompt, model, extra_args, timeout, config_cwd(config["label"]))
            err = ""
        except Exception as e:  # noqa: BLE001
            response, elapsed, err = "", 0.0, str(e)
        (out_dir / "response.md").write_text(response, encoding="utf-8")
        (out_dir.parent / "timing.json").write_text(json.dumps({
            "seconds": round(elapsed, 1), "chars": len(response), "error": err, "model": model or "",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{elapsed:.0f}s, {len(response)}자" + (f", 오류: {err[:80]}" if err else ""))


# ---------- 채점 ----------
def grade_response(response: str, assertions: list[str], judge_model: str | None = None,
                   timeout: int = DEFAULT_TIMEOUT, runner=run_claude) -> str:
    numbered = "\n".join(f"{i}. {a}" for i, a in enumerate(assertions, 1))
    prompt = GRADING_PROMPT.format(assertions=numbered, response=response or "(empty response)")
    text, _ = runner(prompt, judge_model, SAFE_TOOLS_ARGS, timeout, config_cwd("judge"))
    return text


def parse_grades(text: str, expected: int) -> list[dict]:
    """`PASS|n|evidence` 줄만 골라 최대 expected 개. 근거 안의 `|` 는 보존."""
    grades: list[dict] = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-*• ").strip("`")
        m = re.match(r"^(PASS|FAIL)\s*\|\s*(\d+)\s*\|\s*(.*)$", line, re.IGNORECASE)
        if not m:
            continue
        grades.append({"n": int(m.group(2)), "verdict": m.group(1).upper(), "evidence": m.group(3).strip()})
        if len(grades) >= expected:
            break
    return grades


def grade_all(evals: list[dict], configs: list[dict], it_dir: Path, *, judge_model: str | None = None,
              timeout: int = DEFAULT_TIMEOUT, test_filter: int | None = None, runner=run_claude) -> dict:
    totals = {c["label"]: {"pass": 0, "total": 0} for c in configs}
    per_test: list[dict] = []
    for idx, ev in enumerate(evals, 1):
        if test_filter and idx != test_filter:
            continue
        row = {"name": ev["name"], "results": {}}
        for config in configs:
            base = it_dir / ev["name"] / config["label"]
            resp_file = base / "outputs" / "response.md"
            if not resp_file.is_file():
                print(f"  [{ev['name']}] {config['label']}: response.md 없음, 건너뜀")
                continue
            response = resp_file.read_text(encoding="utf-8")
            print(f"  채점 [{ev['name']}] {config['label']} ... ", end="", flush=True)
            try:
                raw = grade_response(response, ev["assertions"], judge_model, timeout, runner=runner)
            except Exception as e:  # noqa: BLE001  채점 실패는 0점으로 기록하고 계속
                raw = f"ERROR: {e}"
                print("채점 실패: " + str(e)[:80], end=" ")
            grades = parse_grades(raw, len(ev["assertions"]))
            passed = sum(1 for g in grades if g["verdict"] == "PASS")
            total = len(ev["assertions"])
            (base / "grading.txt").write_text(raw, encoding="utf-8")
            (base / "grading.json").write_text(json.dumps({
                "pass": passed, "total": total, "grades": grades,
                "assertions": ev["assertions"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            totals[config["label"]]["pass"] += passed
            totals[config["label"]]["total"] += total
            row["results"][config["label"]] = {"pass": passed, "total": total}
            print(f"{passed}/{total}")
        per_test.append(row)

    summary = {"iteration": it_dir.name, "configs": [c["label"] for c in configs], "totals": totals, "tests": per_test}
    (it_dir / "summary.txt").write_text(format_summary(summary), encoding="utf-8")
    (it_dir / "config.json").write_text(json.dumps({
        "configs": configs, "judge_model": judge_model or "", "test_filter": test_filter,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def rate(p: int, t: int) -> str:
    return f"{(100 * p / t):.1f}%" if t else "-"


def format_summary(summary: dict) -> str:
    labels = summary["configs"]
    lines = [f"# {summary['iteration']}", "", "| test | " + " | ".join(labels) + " |", "| --- | " + " | ".join("---" for _ in labels) + " |"]
    for row in summary["tests"]:
        cells = []
        for lb in labels:
            r = row["results"].get(lb)
            cells.append(f"{r['pass']}/{r['total']}" if r else "-")
        lines.append(f"| {row['name']} | " + " | ".join(cells) + " |")
    tot = summary["totals"]
    lines.append("| **pass rate** | " + " | ".join(f"**{rate(tot[lb]['pass'], tot[lb]['total'])}** ({tot[lb]['pass']}/{tot[lb]['total']})" for lb in labels) + " |")
    if len(labels) == 2:
        a, b = labels
        ta, tb = tot[a], tot[b]
        if ta["total"] and tb["total"]:
            delta = 100 * ta["pass"] / ta["total"] - 100 * tb["pass"] / tb["total"]
            lines.append("")
            lines.append(f"delta ({a} - {b}): {delta:+.1f} points")
    return "\n".join(lines) + "\n"


# ---------- main ----------
def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="스킬 평가 실행기 (workspace/<skill>/evals.json)")
    p.add_argument("--skill", required=True, help="skills/<name> 의 name")
    p.add_argument("--test", type=int, help="이 번호의 문제만 (1부터)")
    p.add_argument("--grade-only", action="store_true", help="다시 돌리지 않고 마지막 iteration 을 채점")
    p.add_argument("--with-skill-only", action="store_true", help="baseline 을 건너뜀")
    p.add_argument("--a", help="스킬 버전 A 의 SKILL.md 경로")
    p.add_argument("--a-label")
    p.add_argument("--b", help="스킬 버전 B 의 SKILL.md 경로 (--a 필요)")
    p.add_argument("--b-label")
    p.add_argument("--model", help="평가 대상 claude 모델")
    p.add_argument("--judge-model", help="채점 claude 모델")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="claude 호출당 초 (기본 600)")
    p.add_argument("--allow-actions", action="store_true", help="평가 대상이 Bash/Write/Edit 를 쓰게 둔다")
    p.add_argument("--claude-arg", action="append", default=[], help="claude CLI 에 그대로 넘길 인자 (반복 가능)")
    p.add_argument("--dry-run", action="store_true", help="claude 를 부르지 않고 프롬프트만 출력")
    p.add_argument("--cwd", help="평가 대상 claude 의 작업 폴더 (기본: 저장소 밖 빈 임시 폴더)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data = load_evals(args.skill)
    evals = data["evals"]
    suffix = data.get("suffix", "")
    configs = build_configs(args, args.skill)
    skill_dir = WORKSPACE / args.skill
    it_dir = find_iteration(skill_dir, grade_only=args.grade_only)
    extra = list(args.claude_arg)
    if not args.allow_actions:
        extra = SAFE_TOOLS_ARGS + extra
    global _scratch
    if args.cwd:
        _scratch = Path(args.cwd).resolve()
        _scratch.mkdir(parents=True, exist_ok=True)

    print(f"[evals] skill={args.skill} tests={len(evals)}{f' (only #{args.test})' if args.test else ''} configs={[c['label'] for c in configs]} → {it_dir.relative_to(ROOT)}")
    if not args.dry_run and not args.grade_only:
        # 스킬 폴더를 작업 폴더 안으로 복사 (claude -p 는 작업 폴더 밖 파일을 읽지 못한다)
        for c in configs:
            if c["skill"]:
                c["skill"] = stage_skill(c["skill"], c["label"])
        print(f"[evals] claude cwd = {scratch_dir()}\\<config> (설정마다 따로. baseline 은 빈 폴더, with-skill 은 스킬 사본만)")
    if not args.grade_only:
        if not args.dry_run:
            it_dir.mkdir(parents=True, exist_ok=True)
        for idx, ev in enumerate(evals, 1):
            if args.test and idx != args.test:
                continue
            run_test(ev, configs, it_dir, suffix=suffix, model=args.model, extra_args=extra,
                     timeout=args.timeout, dry_run=args.dry_run)
    if args.dry_run:
        return 0
    print("[evals] 채점")
    summary = grade_all(evals, configs, it_dir, judge_model=args.judge_model, timeout=args.timeout, test_filter=args.test)
    print()
    print(format_summary(summary))
    print(f"[evals] 결과 → {it_dir.relative_to(ROOT)}/summary.txt. 정리는 workspace/{args.skill}/eval-results.md 에.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
