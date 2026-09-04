"""스캐너 단위 테스트 + Python/JS 스캐너 동등성 테스트.

    python -m unittest discover -s .claude/skills/report-viewer/tests
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
VIEWER = SKILL / "engine" / "_viewer"


def load_build():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("rv_build", VIEWER / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scan = load_build()


def make_fixture(root: Path) -> None:
    (root / "work").mkdir()
    (root / "work" / "2026-01-05-weekly.md").write_text(
        "---\ntitle: 주간 보고\ndate: 2026-01-05\ntags: [a, b]\nauthor: 'x'\nmath: true\n---\n\n# 주간 보고\n\n본문 $x$\n", encoding="utf-8")
    (root / "work" / "notes.md").write_text("﻿# 제목만\n\n내용\n", encoding="utf-8")
    (root / "work" / "page.html").write_text("<html><head><title> 페이지  제목 </title></head><body>hi</body></html>", encoding="utf-8")
    (root / "data.json").write_text(json.dumps({"title": "JSON 제목", "n": 1}, ensure_ascii=False), encoding="utf-8")
    (root / "log.txt").write_bytes(b"line1\r\nline2\r\n")  # CRLF 그대로 (text 모드는 OS 줄바꿈으로 바꿔 버림)
    (root / "tool.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "photo.png").write_bytes(b"\x89PNG\r\n")
    (root / "unknown.xyz").write_text("?", encoding="utf-8")
    (root / "_draft.md").write_text("# draft", encoding="utf-8")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "x.md").write_text("# hidden", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "m.js").write_text("x", encoding="utf-8")
    (root / "index.html").write_text("<title>viewer</title>", encoding="utf-8")
    (root / "start.cmd").write_text("@echo off", encoding="utf-8")


class FrontMatterTest(unittest.TestCase):
    def test_parse(self):
        meta, body = scan.parse_front_matter("---\ntitle: T\ntags: [a, b]\nlist:\n  - x\n  - y\nflag: true\n---\nbody\n")
        self.assertEqual(meta["title"], "T")
        self.assertEqual(meta["tags"], ["a", "b"])
        self.assertEqual(meta["list"], ["x", "y"])
        self.assertIs(meta["flag"], True)
        self.assertEqual(body, "body\n")

    def test_no_front_matter(self):
        meta, body = scan.parse_front_matter("# hi\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "# hi\n")

    def test_dates(self):
        self.assertEqual(scan.to_date("2026-1-5"), "2026-01-05")
        self.assertEqual(scan.to_date("2026.09.03-foo.md"), "2026-09-03")
        self.assertIsNone(scan.to_date("nodate.md"))


class WalkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        make_fixture(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def names(self, node):
        out = {}
        for c in node["children"]:
            if c["type"] == "dir":
                out.update(self.names(c))
            else:
                out[c["path"]] = c
        return out

    def test_types_and_skips(self):
        root = scan.walk(self.tmp)
        files = self.names(root)
        self.assertEqual(files["work/2026-01-05-weekly.md"]["title"], "주간 보고")
        self.assertEqual(files["work/2026-01-05-weekly.md"]["tags"], ["a", "b"])
        self.assertEqual(files["work/notes.md"]["title"], "제목만")   # BOM 제거 + H1
        self.assertEqual(files["work/page.html"]["title"], "페이지 제목")
        self.assertEqual(files["data.json"]["title"], "JSON 제목")
        self.assertEqual(files["log.txt"]["type"], "text")
        self.assertEqual(files["log.txt"]["body"], "line1\nline2\n")
        self.assertEqual(files["tool.py"]["type"], "code")
        self.assertEqual(files["tool.py"]["lang"], "python")
        self.assertEqual(files["photo.png"]["type"], "file")
        for skipped in ("unknown.xyz", "_draft.md", ".hidden/x.md", "node_modules/m.js", "index.html", "start.cmd"):
            self.assertNotIn(skipped, files, skipped)

    def test_without_body(self):
        root = scan.walk(self.tmp, with_body=False)
        files = self.names(root)
        self.assertNotIn("body", files["work/2026-01-05-weekly.md"])
        self.assertEqual(files["work/2026-01-05-weekly.md"]["title"], "주간 보고")

    def test_budget(self):
        budget = {"max": 2}
        scan.walk(self.tmp, with_body=False, budget=budget)
        self.assertTrue(budget["truncated"])

    def test_order(self):
        root = scan.walk(self.tmp)
        kinds = [c["type"] == "dir" for c in root["children"]]
        self.assertEqual(kinds, sorted(kinds, reverse=True))  # 폴더 먼저


@unittest.skipIf(shutil.which("node") is None, "node 없음")
class ParityTest(unittest.TestCase):
    """build.py 와 scan.js 가 같은 트리를 내는지 (mtime/ISO 시각은 제외하고 비교)"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        make_fixture(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def strip(n):
        n = dict(n)
        n.pop("mtime", None)
        if "children" in n:
            n["children"] = [ParityTest.strip(c) for c in n["children"]]
        return n

    def test_same_tree(self):
        py_tree = self.strip(scan.walk(self.tmp))
        rules = json.dumps(scan.RULES, ensure_ascii=False)
        js = r"""
const fs=require('fs'),path=require('path');
globalThis.REPORT_FILETYPES=JSON.parse(process.argv[1]);
require(process.argv[2]);
const root=process.argv[3];
const listDir=async rel=>{const abs=path.join(root,rel);return fs.readdirSync(abs,{withFileTypes:true}).map(e=>{const full=path.join(abs,e.name);if(e.isDirectory())return{name:e.name,kind:'dir'};const st=fs.statSync(full);return{name:e.name,kind:'file',size:st.size,mtimeMs:st.mtimeMs,readText:async()=>fs.readFileSync(full,'utf8')};});};
globalThis.ReportScan.walk(listDir,'').then(t=>process.stdout.write(JSON.stringify(t)));
"""
        r = subprocess.run(["node", "-e", js, rules, str(VIEWER / "scan.js"), str(self.tmp)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        js_tree = self.strip(json.loads(r.stdout))
        self.assertEqual(py_tree, js_tree)


if __name__ == "__main__":
    unittest.main()
