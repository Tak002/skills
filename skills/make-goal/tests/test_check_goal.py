"""check_goal.py 단위 테스트 (표준 라이브러리 unittest).

    python -m unittest discover -s skills/make-goal/tests -q
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "check_goal.py"
EXAMPLES = SKILL / "examples.md"


def load_module():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("check_goal", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_goal"] = mod  # dataclass 가 모듈을 찾을 수 있게
    spec.loader.exec_module(mod)
    return mod


cg = load_module()

CLAUDE_BODY = """[목표] `src/auth` 의 세션 만료 버그를 고쳐 만료 후 새로고침하면 /login 으로 이동하는 상태로 만든다.
[완료 조건] 아래 C1–C3 이 모두 참일 때만 완료로 본다.
C1. 재현 테스트 통과 — 확인: `pnpm vitest run src/auth 2>&1 | tail -n 5; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`.
C2. 전체 테스트 회귀 없음 — 확인: `pnpm test 2>&1 | tail -n 5; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`.
C3. 타입체크 — 확인: `pnpm typecheck 2>&1 | tail -n 3; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`.
[증거 규칙] 완료를 주장하는 턴에서 C1–C3 명령을 다시 실행하고 최종 메시지에 `C1 ✅ <근거 원문 한 줄>` 체크리스트를 쓴다.
[제약] (위반하면 미완료) 기존 테스트·설정 수정 금지. 확인: `git diff --stat -- src/auth/__tests__ vitest.config.ts` 출력이 비어 있음.
[범위 밖] 로그인 화면 디자인 변경.
[막힘·중단] 사용자에게 묻지 않는다. 같은 원인으로 3번 연속 실패하면 `GOAL-STATUS: BLOCKED — <원인>`. 턴마다 `GOAL-TURN k/25`, 25턴을 넘기면 `GOAL-STATUS: STOPPED — <남은 일>`(둘 다 종료로 인정).
[참고] (판정 대상 아님) 이슈 #412."""
VALID_CLAUDE = "/goal " + CLAUDE_BODY

VALID_CODEX = """/goal [목표] `app/` 전체를 Pydantic v2 API 로 옮긴 상태로 만든다.
[완료 조건] 현재 worktree 기준으로 모두 참일 때만 update_goal complete:
C1. v1 잔존 0건 — 확인: `grep -rn "pydantic.v1" app/ | wc -l` → `0`.
C2. 테스트 — 확인: `pytest -q` → exit 0.
C3. 타입 — 확인: `mypy app/` → `Success`.
[제약] 테스트 기대값 수정 금지. 확인: `git diff --stat -- tests` 출력이 비어 있음.
[막힘·중단] 같은 원인으로 3턴 연속 진전이 없을 때만 blocked.
[보고] 완료 시 C1–C3 각각을 증명하는 명령과 출력 한 줄을 적는다."""


def replace_line(text: str, prefix: str, new: str | None) -> str:
    """prefix 로 시작하는 줄을 new 로 바꾼다 (None 이면 지운다)."""
    lines = text.split("\n")
    idx = next(i for i, ln in enumerate(lines) if ln.startswith(prefix) or ln.startswith("/goal " + prefix))
    keep_goal = lines[idx].startswith("/goal ")
    if new is None:
        del lines[idx]
        if keep_goal:
            lines[idx] = "/goal " + lines[idx]
    else:
        lines[idx] = ("/goal " if keep_goal else "") + new
    return "\n".join(lines)


def codes(issues) -> list[str]:
    return [i.code for i in issues]


def pad_to(text: str, target: str, length: int, ch: str = "가") -> str:
    """끝에 ' ' + ch 반복을 붙여 정확히 length 가 되게 한다."""
    base = cg.count_length(text, target)
    k, rem = divmod(length - base - 1, cg.units(ch, target))
    assert rem == 0 and k >= 0, (base, length, ch)
    out = text + " " + ch * k
    assert cg.count_length(out, target) == length, (cg.count_length(out, target), length)
    return out


class CountTest(unittest.TestCase):
    def test_hangul_is_one_for_both_targets(self):
        self.assertEqual(cg.count_length("가나다", "claude"), 3)
        self.assertEqual(cg.count_length("가나다", "codex"), 3)

    def test_emoji_is_two_for_claude_one_for_codex(self):
        self.assertEqual(cg.count_length("😀", "claude"), 2)
        self.assertEqual(cg.count_length("😀", "codex"), 1)
        self.assertEqual(cg.count_length("a😀가", "claude"), 4)
        self.assertEqual(cg.count_length("a😀가", "codex"), 3)

    def test_goal_prefix_is_stripped_then_trimmed(self):
        for raw in ("/goal 가나", "/goal\n가나", "  /goal   가나  \n", "/goal\t가나"):
            self.assertEqual(cg.count_length(raw, "claude"), 2, raw)
            self.assertEqual(cg.count_length(raw, "codex"), 2, raw)
        self.assertEqual(cg.count_length("/goal", "claude"), 0)

    def test_goal_prefix_needs_token_boundary_and_leading_position(self):
        self.assertEqual(cg.count_length("/goals 가", "claude"), 8)
        self.assertEqual(cg.count_length("/goal-x 가", "claude"), 9)
        self.assertEqual(cg.count_length("가 /goal 나", "claude"), 9)

    def test_crlf_counts_as_one_newline(self):
        self.assertEqual(cg.count_length("가\r\n나", "claude"), 3)
        self.assertEqual(cg.count_length("가\r나", "codex"), 3)

    def test_trim_follows_each_product(self):
        # JS trim 은 U+FEFF 를 지우고 U+0085 는 남긴다. Rust trim 은 반대.
        self.assertEqual(cg.count_length("﻿가", "claude"), 1)
        self.assertEqual(cg.count_length("﻿가", "codex"), 2)
        self.assertEqual(cg.count_length("\u0085가", "claude"), 2)
        self.assertEqual(cg.count_length("\u0085가", "codex"), 1)
        self.assertEqual(cg.count_length("　가　", "claude"), 1)

    def test_report_example_lengths(self):
        # 연구 보고서 7절이 JS length 로 잰 값과 같아야 한다 (5번 커버리지 예시 원문).
        coverage = """[목표] `src/billing/**` 의 line coverage를 85% 이상으로 올린다(현재 약 61%).
[완료 조건] C1–C4가 모두 참일 때만 완료.
C1. 커버리지 — 확인: `pnpm vitest run src/billing --coverage --coverage.include='src/billing/**' --coverage.reporter=text-summary 2>&1 | tail -n 8` 의 `Lines` ≥ 85%.
C2. 전체 스위트 통과 — 확인: `pnpm test 2>&1 | tail -n 10; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`.
C3. 바뀐 파일은 테스트 파일뿐 — 확인: `git status --porcelain | grep -v -E '\\.test\\.ts$'` 출력이 비어 있음.
C4. 새 테스트마다 동작 검증 `expect`가 있고 스냅샷 전용 테스트가 없다 — 확인: 새 테스트 파일별 `grep -c "expect("` ≥ 1, `grep -c "toMatchSnapshot"` = 0.
[증거 규칙] 시작 시 C1 명령으로 기준선을 출력한다. 완료를 주장하는 턴에서 C1–C4를 다시 실행하고 최종 메시지에 기준선 → 최종 수치와 체크리스트를 쓴다.
[제약] coverage 설정(`vitest.config.ts` include/exclude/thresholds)·`package.json`·소스 코드 수정 금지. `v8 ignore`/`istanbul ignore` 주석 금지. 구현 세부를 복제하지 말고 공개 함수의 입력·출력을 검증한다.
[막힘·중단] 소스 수정 없이는 85%가 불가능하다고 판단되면 근거(미도달 파일·라인)를 적고 `GOAL-STATUS: BLOCKED — <원인>`. 턴마다 `GOAL-TURN k/30`, 30턴 초과 시 `GOAL-STATUS: STOPPED — <현재 수치>`(둘 다 종료로 인정)."""
        self.assertEqual(cg.count_length(coverage, "claude"), 966)

    def test_code_fence_is_removed(self):
        res = cg.check("```text\n" + VALID_CLAUDE + "\n```", "claude")
        self.assertEqual(res.length, cg.count_length(VALID_CLAUDE, "claude"))
        self.assertTrue(any("울타리" in n for n in res.notes))
        self.assertEqual(res.errors, [])


class ErrorTest(unittest.TestCase):
    def test_valid_goals_have_no_issues(self):
        for text, target in ((VALID_CLAUDE, "claude"), (VALID_CODEX, "codex")):
            res = cg.check(text, target)
            self.assertEqual(res.errors, [], target)
            self.assertEqual(res.warnings, [], target)
            self.assertTrue(res.ok)
            self.assertEqual(res.c_numbers, [1, 2, 3])

    def test_length_limit_boundary(self):
        at_limit = pad_to(VALID_CLAUDE, "claude", 4000)
        self.assertNotIn("length", codes(cg.check(at_limit, "claude").errors))
        over = at_limit + "가"
        res = cg.check(over, "claude")
        self.assertIn("length", codes(res.errors))
        self.assertEqual(res.length, 4001)
        self.assertFalse(res.ok)

    def test_limit_option_and_emoji_units(self):
        text = pad_to(VALID_CODEX, "codex", 4000, "😀")
        self.assertNotIn("length", codes(cg.check(text, "codex").errors))
        self.assertIn("length", codes(cg.check(text, "claude").errors))  # 이모지는 claude 에서 2
        self.assertNotIn("length", codes(cg.check(text + "가" * 500, "codex", limit=5000).errors))

    def test_required_sections(self):
        for header in ("[목표]", "[완료 조건]", "[증거 규칙]", "[제약]", "[막힘·중단]"):
            res = cg.check(replace_line(VALID_CLAUDE, header, None), "claude")
            missing = [e.message for e in res.errors if e.code == "section-missing"]
            self.assertEqual(len(missing), 1, header)
            self.assertIn(header, missing[0])

    def test_evidence_section_required_only_for_claude(self):
        self.assertNotIn("section-missing", codes(cg.check(VALID_CODEX, "codex").errors))
        res = cg.check(replace_line(VALID_CODEX, "[보고]", None), "claude")
        self.assertIn("필수 섹션 [증거 규칙] 이 없다.", [e.message for e in res.errors])

    def test_optional_sections_are_optional(self):
        text = replace_line(replace_line(VALID_CLAUDE, "[범위 밖]", None), "[참고]", None)
        self.assertEqual(cg.check(text, "claude").errors, [])

    def test_no_c_items(self):
        text = VALID_CLAUDE
        for k in (1, 2, 3):
            text = replace_line(text, f"C{k}.", None)
        self.assertIn("no-c-items", codes(cg.check(text, "claude").errors))

    def test_c_item_without_check_word(self):
        text = replace_line(VALID_CLAUDE, "C2.", "C2. 전체 테스트 `pnpm test` → `EXIT=0`.")
        errs = [e for e in cg.check(text, "claude").errors if e.code == "c-no-check"]
        self.assertEqual(len(errs), 1)
        self.assertIn("C2", errs[0].message)

    def test_template_tokens(self):
        for token in ("{명령}", "{N}", "{n}", "{…}", "{보호 경로}"):
            text = replace_line(VALID_CLAUDE, "C3.", f"C3. 타입체크 — 확인: `pnpm typecheck {token}` → `EXIT=0`.")
            self.assertIn("template-token", codes(cg.check(text, "claude").errors), token)
        text = VALID_CLAUDE.replace("[참고] (판정 대상 아님) 이슈 #412.", "…(3–7개)\n[참고] (판정 대상 아님) 이슈 #412.")
        self.assertIn("template-token", codes(cg.check(text, "claude").errors))

    def test_shell_braces_are_not_template_tokens(self):
        safe = ("C3. 타입체크 — 확인: `grep -cE '[0-9]{3}' a.txt; find . -name x -exec rm {} \\; "
                "curl -d '{\"name\": \"가\"}' x; awk '{print $1}' f` → `EXIT=0`.")
        res = cg.check(replace_line(VALID_CLAUDE, "C3.", safe), "claude")  # ${PIPESTATUS[0]} 도 들어 있음
        self.assertNotIn("template-token", codes(res.errors))

    def test_goal_status_required_for_claude_only(self):
        text = replace_line(VALID_CLAUDE, "[막힘·중단]", "[막힘·중단] 사용자에게 묻지 않는다. 막히면 원인을 적는다.")
        self.assertIn("no-goal-status", codes(cg.check(text, "claude").errors))
        self.assertNotIn("no-goal-status", codes(cg.check(VALID_CODEX, "codex").errors))

    def test_empty_goal(self):
        for raw in ("", "   ", "/goal", "/goal \n "):
            res = cg.check(raw, "claude")
            self.assertEqual(codes(res.errors), ["empty"], repr(raw))


class WarningTest(unittest.TestCase):
    def warn(self, text: str, target: str = "claude", **kw) -> list[str]:
        res = cg.check(text, target, **kw)
        self.assertEqual(res.errors, [], [e.message for e in res.errors])
        return codes(res.warnings)

    def test_soft_length(self):
        self.assertEqual(self.warn(pad_to(VALID_CLAUDE, "claude", 3500)), [])
        self.assertIn("length-soft", self.warn(pad_to(VALID_CLAUDE, "claude", 3501)))

    def test_goal_and_criteria_within_first_500(self):
        text = "/goal [참고] (판정 대상 아님) " + "가" * 600 + "\n" + replace_line(CLAUDE_BODY, "[참고]", None)
        w = [x for x in cg.check(text, "claude").warnings if x.code == "front-500"]
        self.assertEqual(len(w), 2)
        self.assertIn("[목표]", w[0].message)
        self.assertIn("[완료 조건]", w[1].message)

    def test_c_count(self):
        def goal_with(nums):
            items = "\n".join(f"C{k}. 상태 {k} — 확인: `pnpm test --run t{k}` → `EXIT=0`." for k in nums)
            head, _, rest = VALID_CLAUDE.partition("C1.")
            rest = rest[rest.index("[증거 규칙]"):]
            return head + items + "\n" + rest
        self.assertIn("c-count", self.warn(goal_with([1, 2])))
        self.assertIn("c-count", self.warn(goal_with(range(1, 9))))
        self.assertNotIn("c-count", self.warn(goal_with(range(1, 8))))
        self.assertIn("c-numbering", self.warn(goal_with([1, 2, 4])))

    def test_c_item_without_command_or_expected(self):
        text = replace_line(VALID_CLAUDE, "C3.", "C3. 타입체크 — 확인: 타입 오류 → 0건.")
        self.assertEqual(self.warn(text), ["c-no-command"])
        text = replace_line(VALID_CLAUDE, "C3.", "C3. 린트 — 확인: `pnpm lint` 출력을 인용.")
        self.assertEqual(self.warn(text), ["c-no-expected"])

    def test_judge_cannot_read_files_claude_only(self):
        item = "C3. 명세 반영 — 확인: `docs/spec.md` 의 체크리스트가 모두 [x] → 남은 항목 0건."
        self.assertEqual(self.warn(replace_line(VALID_CLAUDE, "C3.", item)), ["judge-file-only"])
        self.assertEqual(self.warn(replace_line(VALID_CODEX, "C3.", item), "codex"), ["c-no-command"])

    def test_subjective_words_only_in_goal_and_criteria(self):
        text = replace_line(VALID_CLAUDE, "[목표]", "[목표] `src/auth` 를 깔끔하게 정리해 세션 만료가 잘 처리되는 상태로 만든다.")
        msgs = [w.message for w in cg.check(text, "claude").warnings if w.code == "subjective"]
        self.assertEqual(len(msgs), 2)
        self.assertTrue(any("'깔끔'" in m for m in msgs))
        self.assertTrue(any("'잘'" in m for m in msgs))
        text = replace_line(VALID_CLAUDE, "[제약]", "[제약] 성능 최적화·개선 작업 금지. 확인: `git diff --stat -- src/perf` 출력이 비어 있음.")
        self.assertEqual(self.warn(text), [])

    def test_jal_inside_other_words_is_not_subjective(self):
        text = replace_line(VALID_CLAUDE, "[목표]", "[목표] 긴 로그를 잘라 저장하고 잘못된 세션 값을 없앤 상태로 만든다.")
        self.assertEqual(self.warn(text), [])

    def test_codex_turn_cap(self):
        text = replace_line(VALID_CODEX, "[막힘·중단]", "[막힘·중단] 30턴을 넘기면 중단한다.")
        self.assertIn("codex-turn-cap", self.warn(text, "codex"))
        text = replace_line(VALID_CODEX, "[막힘·중단]", "[막힘·중단] 턴마다 `GOAL-TURN k/30` 을 쓴다. 같은 원인으로 3턴 연속 진전이 없을 때만 blocked.")
        self.assertIn("codex-turn-cap", self.warn(text, "codex"))
        self.assertNotIn("codex-turn-cap", self.warn(VALID_CODEX, "codex"))  # "3턴 연속" 은 상한이 아니다

    def test_codex_without_report(self):
        self.assertEqual(self.warn(replace_line(VALID_CODEX, "[보고]", None), "codex"), ["codex-no-report"])

    def test_shell_idioms(self):
        self.assertEqual(self.warn(VALID_CLAUDE, shell="bash"), [])
        ps = cg.check(VALID_CLAUDE, "claude", shell="powershell").warnings
        self.assertTrue(any(w.code == "shell-idiom" and "PIPESTATUS" in w.message for w in ps))
        dollar_q = replace_line(VALID_CLAUDE, "C3.", 'C3. 타입체크 — 확인: `pnpm typecheck; echo "EXIT=$?"` → `EXIT=0`.')
        ps = cg.check(dollar_q, "claude", shell="powershell").warnings
        self.assertTrue(any(w.code == "shell-idiom" and "True/False" in w.message for w in ps))
        self.assertEqual(self.warn(dollar_q, shell="bash"), [])  # 파이프 없는 $? 는 bash 에서 괜찮다
        lec = replace_line(VALID_CLAUDE, "C3.", 'C3. 타입체크 — 확인: `pnpm typecheck; "EXIT=$LASTEXITCODE"` → `EXIT=0`.')
        self.assertIn("shell-idiom", self.warn(lec, shell="bash"))
        ps = cg.check(lec, "claude", shell="powershell").warnings
        self.assertFalse(any("LASTEXITCODE 가 없다" in w.message for w in ps))
        piped = replace_line(VALID_CLAUDE, "C3.", 'C3. 타입체크 — 확인: `pnpm typecheck 2>&1 | tail -n 3; echo "EXIT=$?"` → `EXIT=0`.')
        self.assertIn("shell-idiom", self.warn(piped, shell="bash"))

    def test_constraint_without_check(self):
        text = replace_line(VALID_CLAUDE, "[제약]", "[제약] 기존 테스트·설정 수정 금지.")
        self.assertEqual(self.warn(text), ["constraint-no-check"])

    def test_evidence_without_rerun(self):
        text = replace_line(VALID_CLAUDE, "[증거 규칙]", "[증거 규칙] 최종 메시지에 체크리스트를 쓴다.")
        self.assertEqual(self.warn(text), ["evidence-rerun"])

    def test_claude_without_turn_cap(self):
        text = replace_line(VALID_CLAUDE, "[막힘·중단]", "[막힘·중단] 같은 원인으로 3번 연속 실패하면 `GOAL-STATUS: BLOCKED — <원인>`.")
        self.assertEqual(self.warn(text), ["no-turn-cap"])

    def test_limit_above_4000_adds_note(self):
        res = cg.check(VALID_CLAUDE, "claude", limit=5000)
        self.assertTrue(any("4,000" in n and "OpenChamber" in n for n in res.notes))
        self.assertEqual(res.soft_limit, 3500)
        self.assertEqual(cg.check(VALID_CLAUDE, "claude", limit=1000).soft_limit, 875)


class ParseTest(unittest.TestCase):
    def test_section_aliases(self):
        for alias in ("[막힘]", "[막힘 / 중단]", "[막힘ㆍ중단]", "[막힘 · 중단]", "[중단]"):
            res = cg.check(VALID_CLAUDE.replace("[막힘·중단]", alias), "claude")
            self.assertEqual(res.errors, [], alias)
        self.assertEqual(cg.check(VALID_CLAUDE.replace("[완료 조건]", "[완료조건]"), "claude").errors, [])

    def test_mid_line_mention_is_not_a_header(self):
        text = replace_line(VALID_CLAUDE, "[증거 규칙]", "[증거 규칙] 완료를 주장하는 턴에서 [완료 조건] 의 명령을 다시 실행한다.")
        res = cg.check(text, "claude")
        self.assertEqual(res.errors, [])
        self.assertEqual(res.c_numbers, [1, 2, 3])
        self.assertEqual([n for n, _ in res.sections], ["목표", "완료 조건", "증거 규칙", "제약", "범위 밖", "막힘·중단", "참고"])

    def test_inline_c_items(self):
        line = ("[완료 조건] 모두 참일 때만 완료. C1. A — 확인: `pnpm a` → `EXIT=0`. "
                "C2. B — 확인: `pnpm b` → `EXIT=0`. C3. C — 확인: `pnpm c` → `EXIT=0`.")
        text = VALID_CLAUDE
        for k in (1, 2, 3):
            text = replace_line(text, f"C{k}.", None)
        text = replace_line(text, "[완료 조건]", line)
        res = cg.check(text, "claude")
        self.assertEqual(res.c_numbers, [1, 2, 3])
        self.assertEqual(res.errors, [])

    def test_section_lengths_sum_to_total(self):
        res = cg.check(VALID_CLAUDE, "claude")
        self.assertEqual(sum(ln for _, ln in res.sections), res.length)


class CliTest(unittest.TestCase):
    def run_cli(self, *args: str, stdin: bytes | None = None) -> tuple[int, str, str]:
        proc = subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, timeout=60)
        return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8", "replace")

    def write(self, text: str | bytes) -> str:
        d = Path(tempfile.mkdtemp(prefix="check-goal-"))
        p = d / "goal.txt"
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text, encoding="utf-8")
        self.addCleanup(lambda: (p.unlink(), d.rmdir()))
        return str(p)

    def test_pass_prints_length_line(self):
        code, out, _ = self.run_cli(self.write(VALID_CLAUDE))
        self.assertEqual(code, 0)
        n = cg.count_length(VALID_CLAUDE, "claude")
        self.assertTrue(out.startswith(f"길이: {n:,} / 4,000자 (claude, UTF-16 기준) · 검사 통과"), out)

    def test_codex_label(self):
        code, out, _ = self.run_cli(self.write(VALID_CODEX), "--target", "codex")
        self.assertEqual(code, 0)
        self.assertIn("(codex, 문자 수 기준) · 검사 통과", out.splitlines()[0])

    def test_errors_exit_1(self):
        code, out, _ = self.run_cli(self.write(replace_line(VALID_CLAUDE, "[제약]", None)))
        self.assertEqual(code, 1)
        self.assertIn("검사 실패", out)
        self.assertIn("[section-missing]", out)

    def test_json_mode(self):
        code, out, _ = self.run_cli(self.write(pad_to(VALID_CLAUDE, "claude", 4100)), "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["length"], 4100)
        self.assertEqual(data["over"], 100)
        self.assertEqual(data["unit"], "utf16")
        self.assertFalse(data["ok"])
        self.assertEqual([e["code"] for e in data["errors"]], ["length"])
        self.assertEqual(data["c_items"], [1, 2, 3])

    def test_stdin_with_bom_and_crlf(self):
        raw = ("﻿" + VALID_CODEX.replace("\n", "\r\n")).encode("utf-8")
        code, out, _ = self.run_cli("-", "--target", "codex", "--json", stdin=raw)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["length"], cg.count_length(VALID_CODEX, "codex"))

    def test_limit_option(self):
        path = self.write(pad_to(VALID_CLAUDE, "claude", 4500))
        self.assertEqual(self.run_cli(path)[0], 1)
        code, out, _ = self.run_cli(path, "--limit", "5000")
        self.assertEqual(code, 0)
        self.assertIn("/ 5,000자", out)
        self.assertIn("OpenChamber", out)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.run_cli("no-such-goal-file.txt")[0], 2)
        self.assertEqual(self.run_cli(self.write(VALID_CLAUDE), "--target", "gemini")[0], 2)
        self.assertEqual(self.run_cli(self.write(VALID_CLAUDE), "--limit", "0")[0], 2)
        self.assertEqual(self.run_cli(self.write(b"\xff\xfe\x00bad"))[0], 2)
        self.assertEqual(self.run_cli()[0], 2)


class TemplateTest(unittest.TestCase):
    """reference.md 의 골격은 자리표시만 채우면 통과하도록 구조가 완전해야 한다 (필수 섹션, C 항목, 확인, GOAL-STATUS)."""

    def blocks(self, path: Path, anchor: str) -> str:
        text = path.read_text(encoding="utf-8")
        m = re.search(r"(?m)^( *)```text\n(.*?)\n\1```", text[text.index(anchor):], re.S)
        indent = m.group(1)
        return "\n".join(ln[len(indent):] if ln.startswith(indent) else ln for ln in m.group(2).split("\n"))

    def test_templates_only_miss_placeholders(self):
        for path, anchor in ((SKILL / "reference.md", "### 3.1"), (SKILL / "reference.md", "런처 골격:"),
                             (SKILL / "SKILL.md", "**초안을 쓴다.**")):
            with self.subTest(anchor=anchor):
                res = cg.check(self.blocks(path, anchor), "claude")
                self.assertTrue(set(codes(res.errors)) <= {"template-token"}, [e.message for e in res.errors])


class ExamplesTest(unittest.TestCase):
    """examples.md 의 좋은 goal 은 모두 오류·경고 없이 통과하고, 제목의 길이가 실제와 같아야 한다."""

    BLOCK_RE = re.compile(r"<!--\s*goal:\s*(claude|codex)\s*-->\s*\n```text\n(.*?)\n```", re.S)
    LABEL_RE = re.compile(r"좋은 예 \((?:Claude Code|Codex), ([\d,]+)자\)")

    def test_examples_pass(self):
        md = EXAMPLES.read_text(encoding="utf-8")
        blocks = list(self.BLOCK_RE.finditer(md))
        self.assertEqual([b.group(1) for b in blocks], ["claude"] * 6 + ["codex"])
        for b in blocks:
            target, body = b.group(1), b.group(2)
            with self.subTest(start=body[:40]):
                self.assertTrue(body.startswith("/goal "))
                res = cg.check(body, target)
                self.assertEqual([e.message for e in res.errors], [])
                self.assertEqual([w.message for w in res.warnings], [])
                labels = self.LABEL_RE.findall(md[: b.start()])
                self.assertTrue(labels)
                self.assertEqual(int(labels[-1].replace(",", "")), res.length)


if __name__ == "__main__":
    unittest.main()
