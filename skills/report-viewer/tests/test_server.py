"""serve.py 연기 테스트: 임시 폴더에 설치 → 서버 기동 → API 확인."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent


def get(url, method="GET", body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, (json.loads(r.read().decode("utf-8")) if r.headers.get_content_type() == "application/json" else r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.project = cls.tmp / "proj"
        cls.project.mkdir()
        r = subprocess.run([sys.executable, str(SKILL / "scripts" / "setup.py"), "--project-dir", str(cls.project), "--dest", "report", "--no-hook", "--no-claude-md"],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stdout + r.stderr
        cls.report = cls.project / "report"
        (cls.report / "work" / "2026-02-01-test.md").write_text("---\ntitle: 테스트 문서\ndate: 2026-02-01\n---\n\n# 테스트 문서\n\n검색어 pineapple\n", encoding="utf-8")
        (cls.report / "personal" / "page.html").write_text("<title>페이지</title><p>x</p>", encoding="utf-8")
        other = cls.tmp / "other"
        other.mkdir()
        (other / "tool.py").write_text("def f():\n    return 'kiwi'\n", encoding="utf-8")
        cls.other = other
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        cls.proc = subprocess.Popen([sys.executable, str(cls.report / "_viewer" / "serve.py"), "--no-open", "--port", "0"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)
        # 첫 줄에서 포트를 읽는다
        line = ""
        for _ in range(100):
            line = cls.proc.stdout.readline()
            if "http://127.0.0.1:" in line:
                break
        cls.port = int(line.split("http://127.0.0.1:")[1].split("/")[0])
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(50):
            try:
                get(cls.base + "/api/ping")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.kill()
        cls.proc.wait()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_ping_and_tree(self):
        st, j = get(self.base + "/api/ping")
        self.assertEqual(st, 200)
        self.assertEqual(j["app"], "report-viewer")
        self.assertIn("categories", j["config"])
        st, t = get(self.base + "/api/tree?root=report")
        self.assertEqual(st, 200)
        self.assertTrue(t["lazy"])
        names = {c["name"] for c in t["root"]["children"]}
        self.assertIn("work", names)
        self.assertNotIn("_viewer", names)
        self.assertNotIn("index.html", names)
        work = next(c for c in t["root"]["children"] if c["name"] == "work")
        md = next(c for c in work["children"] if c["name"].endswith("test.md"))
        self.assertEqual(md["title"], "테스트 문서")
        self.assertNotIn("body", md)

    def test_file_and_search(self):
        st, f = get(self.base + "/api/file?root=report&path=work/2026-02-01-test.md")
        self.assertEqual(st, 200)
        self.assertIn("pineapple", f["body"])
        st, s = get(self.base + "/api/search?root=report&q=pineapple")
        self.assertEqual([h["path"] for h in s["hits"]], ["work/2026-02-01-test.md"])
        self.assertIn("pineapple", s["hits"][0]["snippet"])

    def test_raw_and_static(self):
        st, body = get(self.base + "/raw/report/personal/page.html")
        self.assertEqual(st, 200)
        self.assertIn(b"<title>", body)
        st, _ = get(self.base + "/")
        self.assertEqual(st, 200)
        st, _ = get(self.base + "/_viewer/app.js")
        self.assertEqual(st, 200)

    def test_traversal_blocked(self):
        self.assertEqual(get(self.base + "/raw/report/../_viewer/serve.py")[0], 404)
        self.assertEqual(get(self.base + "/api/file?root=report&path=../other/tool.py")[0], 404)
        self.assertEqual(get(self.base + "/raw/nope/x")[0], 404)

    def test_roots_add_browse_remove(self):
        st, j = get(self.base + "/api/roots", "POST", {"path": str(self.other), "name": "Other"})
        self.assertEqual(st, 200)
        rid = j["added"]["id"]
        self.assertTrue((self.report / "_roots.json").exists())
        st, t = get(self.base + f"/api/tree?root={rid}")
        self.assertEqual(t["root"]["children"][0]["type"], "code")
        st, s = get(self.base + f"/api/search?root={rid}&q=kiwi")
        self.assertEqual(len(s["hits"]), 1)
        self.assertEqual(s["hits"][0]["ext"], ".py")
        st, b = get(self.base + "/api/browse?path=" + str(self.tmp))
        self.assertIn("other", [d["name"] for d in b["dirs"]])
        st, b = get(self.base + "/api/browse?path=")
        self.assertTrue(b["drives"])
        st, j = get(self.base + f"/api/roots/{rid}", "DELETE")
        self.assertTrue(j["removed"])
        self.assertEqual(get(self.base + "/api/roots/report", "DELETE")[1]["removed"], False)

    def test_setup_idempotent_and_preserves(self):
        cfg = self.report / "_config.json"
        cfg.write_text(json.dumps({"title": "내 보고서", "port": 8765, "categories": {"work": "W"}, "defaultCategory": "work"}), encoding="utf-8")
        marker = self.report / "_viewer" / "user-edit.txt"
        marker.write_text("x", encoding="utf-8")
        r = subprocess.run([sys.executable, str(SKILL / "scripts" / "setup.py"), "--project-dir", str(self.project), "--no-hook", "--no-claude-md"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8"))["title"], "내 보고서")   # 사용자 설정 보존
        self.assertFalse(marker.exists())                                                     # _viewer 는 교체
        self.assertTrue((self.report / "work" / "2026-02-01-test.md").exists())            # 문서 보존


if __name__ == "__main__":
    unittest.main()
