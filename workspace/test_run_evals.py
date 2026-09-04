"""run_evals.py 의 단위 테스트. claude 호출은 가짜 runner 로 대체한다. 표준 라이브러리 unittest 만 쓴다.

실행 (저장소 루트에서):  python -m unittest discover -s workspace -q
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_evals as re_  # noqa: E402


def make_ws(tmp: Path, skill: str = "demo", evals=None) -> Path:
    evals = evals or [
        {"id": 1, "name": "first-case", "prompt": "설명해줘", "assertions": ["A", "B"]},
        {"id": 2, "name": "second-case", "prompt": "요약해줘", "assertions": ["C", "D", "E"]},
    ]
    d = tmp / skill
    d.mkdir()
    (d / "evals.json").write_text(json.dumps({"skill_name": skill, "evals": evals}), encoding="utf-8")
    return tmp


def args(**kw):
    base = dict(a=None, a_label=None, b=None, b_label=None, with_skill_only=False)
    base.update(kw)
    return SimpleNamespace(**base)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class TestLoadEvals(TmpCase):
    def test_loads_from_json(self):
        ws = make_ws(self.tmp)
        data = re_.load_evals("demo", workspace=ws)
        self.assertEqual(len(data["evals"]), 2)
        self.assertEqual(data["evals"][1]["assertions"], ["C", "D", "E"])

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            re_.load_evals("nope", workspace=self.tmp)

    def test_validate_rejects_bad_shape(self):
        errs = re_.validate_evals({"skill_name": "x", "evals": [{"id": 1, "name": "Bad Name", "prompt": "p", "assertions": []}]}, "y")
        joined = " ".join(errs)
        self.assertIn("skill_name", joined)
        self.assertIn("kebab-case", joined)
        self.assertIn("assertions", joined)

    def test_validate_ok(self):
        self.assertEqual(re_.validate_evals({"skill_name": "x", "evals": [{"id": 1, "name": "ok", "prompt": "p", "assertions": ["a"]}]}, "x"), [])


class TestFindIteration(TmpCase):
    def test_first(self):
        self.assertEqual(re_.find_iteration(self.tmp).name, "iteration-1")

    def test_next(self):
        (self.tmp / "iteration-1").mkdir()
        (self.tmp / "iteration-3").mkdir()
        self.assertEqual(re_.find_iteration(self.tmp).name, "iteration-4")

    def test_grade_only_latest(self):
        (self.tmp / "iteration-2").mkdir()
        (self.tmp / "iteration-10").mkdir()
        self.assertEqual(re_.find_iteration(self.tmp, grade_only=True).name, "iteration-10")

    def test_grade_only_none(self):
        with self.assertRaises(FileNotFoundError):
            re_.find_iteration(self.tmp, grade_only=True)


class TestParseGrades(unittest.TestCase):
    def test_clean(self):
        g = re_.parse_grades("PASS|1|good\nFAIL|2|bad", 2)
        self.assertEqual([x["verdict"] for x in g], ["PASS", "FAIL"])
        self.assertEqual(g[1]["evidence"], "bad")

    def test_caps_and_ignores_noise(self):
        text = "Here are grades:\nPASS|1|a\n- PASS|2|b\nPASS|3|c\nDone."
        self.assertEqual(len(re_.parse_grades(text, 2)), 2)

    def test_pipes_in_evidence(self):
        g = re_.parse_grades("PASS|1|uses `a | b` syntax", 1)
        self.assertEqual(g[0]["evidence"], "uses `a | b` syntax")

    def test_empty(self):
        self.assertEqual(re_.parse_grades("", 3), [])

    def test_case_and_spaces(self):
        g = re_.parse_grades("  pass | 1 | ok  ", 1)
        self.assertEqual((g[0]["verdict"], g[0]["n"]), ("PASS", 1))


class TestBuildConfigs(unittest.TestCase):
    def test_default(self):
        c = re_.build_configs(args(), "demo")
        self.assertEqual([x["label"] for x in c], ["with-skill", "baseline"])
        self.assertTrue(Path(c[0]["skill"]).is_absolute())
        self.assertTrue(c[0]["skill"].replace("\\", "/").endswith("skills/demo/SKILL.md"))
        self.assertIsNone(c[1]["skill"])

    def test_with_skill_only(self):
        self.assertEqual([x["label"] for x in re_.build_configs(args(with_skill_only=True), "demo")], ["with-skill"])

    def test_ab(self):
        c = re_.build_configs(args(a="v1/SKILL.md", b="v2/SKILL.md", a_label="old", b_label="new"), "demo")
        self.assertEqual([x["label"] for x in c], ["old", "new"])
        self.assertTrue(all(Path(x["skill"]).is_absolute() for x in c))
        self.assertTrue(c[1]["skill"].replace("\\", "/").endswith("v2/SKILL.md"))

    def test_b_without_a(self):
        with self.assertRaises(ValueError):
            re_.build_configs(args(b="v2/SKILL.md"), "demo")


class TestStageSkill(TmpCase):
    def test_copies_skill_without_secrets(self):
        src = self.tmp / "src" / "my-skill"
        (src / "scripts" / "node_modules" / "x").mkdir(parents=True)
        (src / "SKILL.md").write_text("---\nname: my-skill\n---\n", encoding="utf-8")
        (src / "scripts" / ".env").write_text("NOTION_TOKEN_V2=secret", encoding="utf-8")
        (src / "scripts" / "run.mjs").write_text("// ok", encoding="utf-8")
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        staged = Path(re_.stage_skill(str(src / "SKILL.md"), "with-skill", scratch))
        self.assertTrue(staged.is_file())
        self.assertTrue(str(staged).startswith(str(scratch / "with-skill")))
        self.assertFalse((scratch / "baseline" / "skills").exists())
        self.assertTrue((staged.parent / "scripts" / "run.mjs").is_file())
        self.assertFalse((staged.parent / "scripts" / ".env").exists())
        self.assertFalse((staged.parent / "scripts" / "node_modules").exists())


class TestRunTest(TmpCase):
    def test_writes_outputs_and_prompts(self):
        ev = {"id": 1, "name": "case", "prompt": "질문", "assertions": ["a"]}
        configs = re_.build_configs(args(), "demo")
        seen, cwds = [], []

        def fake(prompt, model, extra, timeout, cwd=None):
            seen.append(prompt)
            cwds.append(cwd)
            return "답변", 1.5

        re_._scratch = self.tmp / "scratch"
        with contextlib.redirect_stdout(io.StringIO()):
            re_.run_test(ev, configs, self.tmp, suffix="설명만", runner=fake)
        # 설정마다 다른 작업 폴더
        self.assertEqual(len(set(map(str, cwds))), 2)
        self.assertTrue(all(str(c).startswith(str(self.tmp / "scratch")) for c in cwds))
        self.assertEqual((self.tmp / "case" / "with-skill" / "outputs" / "response.md").read_text(encoding="utf-8"), "답변")
        timing = json.loads((self.tmp / "case" / "baseline" / "timing.json").read_text(encoding="utf-8"))
        self.assertEqual((timing["seconds"], timing["error"]), (1.5, ""))
        self.assertIn("SKILL.md", seen[0])
        self.assertIn("설명만", seen[0])
        self.assertNotIn("SKILL.md", seen[1])
        self.assertTrue(seen[1].startswith("질문"))

    def test_error_recorded(self):
        ev = {"id": 1, "name": "case", "prompt": "q", "assertions": ["a"]}

        def boom(*_):
            raise RuntimeError("claude down")

        re_._scratch = self.tmp / "scratch"
        with contextlib.redirect_stdout(io.StringIO()):
            re_.run_test(ev, [{"label": "x", "skill": None}], self.tmp, runner=boom)
        timing = json.loads((self.tmp / "case" / "x" / "timing.json").read_text(encoding="utf-8"))
        self.assertIn("claude down", timing["error"])

    def test_dry_run_writes_nothing(self):
        ev = {"id": 1, "name": "case", "prompt": "q", "assertions": ["a"]}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            re_.run_test(ev, [{"label": "x", "skill": None}], self.tmp, dry_run=True, runner=lambda *a: ("", 0))
        self.assertFalse((self.tmp / "case").exists())
        self.assertIn("q", buf.getvalue())


class TestGradeAll(TmpCase):
    def _prep(self):
        evals = [{"id": 1, "name": "case", "prompt": "q", "assertions": ["a", "b"]}]
        configs = re_.build_configs(args(), "demo")
        for c in configs:
            d = self.tmp / "case" / c["label"] / "outputs"
            d.mkdir(parents=True)
            (d / "response.md").write_text("resp " + c["label"], encoding="utf-8")
        return evals, configs

    def test_writes_grading_and_summary(self):
        evals, configs = self._prep()

        def judge(prompt, model, extra, timeout, cwd=None):
            return ("PASS|1|x\nPASS|2|y" if "with-skill" in prompt else "PASS|1|x\nFAIL|2|z"), 0.1

        re_._scratch = self.tmp / "scratch"
        with contextlib.redirect_stdout(io.StringIO()):
            s = re_.grade_all(evals, configs, self.tmp, runner=judge)
        self.assertEqual(s["totals"]["with-skill"], {"pass": 2, "total": 2})
        self.assertEqual(s["totals"]["baseline"], {"pass": 1, "total": 2})
        g = json.loads((self.tmp / "case" / "baseline" / "grading.json").read_text(encoding="utf-8"))
        self.assertEqual((g["pass"], g["grades"][1]["verdict"]), (1, "FAIL"))
        summary = (self.tmp / "summary.txt").read_text(encoding="utf-8")
        for token in ("100.0%", "50.0%", "+50.0 points"):
            self.assertIn(token, summary)
        self.assertTrue((self.tmp / "config.json").is_file())

    def test_skips_missing_response(self):
        evals = [{"id": 1, "name": "case", "prompt": "q", "assertions": ["a"]}]
        re_._scratch = self.tmp / "scratch"
        with contextlib.redirect_stdout(io.StringIO()):
            s = re_.grade_all(evals, [{"label": "x", "skill": None}], self.tmp, runner=lambda *a: ("PASS|1|e", 0))
        self.assertEqual(s["totals"]["x"], {"pass": 0, "total": 0})

    def test_test_filter(self):
        evals = [
            {"id": 1, "name": "one", "prompt": "q", "assertions": ["a"]},
            {"id": 2, "name": "two", "prompt": "q", "assertions": ["a"]},
        ]
        for n in ("one", "two"):
            d = self.tmp / n / "x" / "outputs"
            d.mkdir(parents=True)
            (d / "response.md").write_text("r", encoding="utf-8")
        re_._scratch = self.tmp / "scratch"
        with contextlib.redirect_stdout(io.StringIO()):
            s = re_.grade_all(evals, [{"label": "x", "skill": None}], self.tmp, test_filter=2, runner=lambda *a: ("PASS|1|e", 0))
        self.assertEqual([t["name"] for t in s["tests"]], ["two"])


if __name__ == "__main__":
    unittest.main()
