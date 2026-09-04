#!/usr/bin/env python3
"""
_viewer/serve.py — 보고서 뷰어 로컬 서버 (권장 실행 방법)

    python _viewer/serve.py             # 서버 시작 + 브라우저 자동 열기 (보통은 start.cmd / start.sh 로 실행)
    python _viewer/serve.py --no-open
    python _viewer/serve.py --port 9000

색인 없이 폴더를 직접 읽는다. 기본 폴더는 이 뷰어가 설치된 보고서 폴더이고,
뷰어의 "폴더 추가" 로 PC 안의 어떤 폴더든 등록할 수 있다 (목록: 보고서 폴더의 _roots.json).
설정은 보고서 폴더의 _config.json (title, port, categories). 127.0.0.1 에만 바인딩한다.

API:
  GET  /api/ping                      살아 있는지 + 설정
  GET  /api/roots                     등록된 폴더 목록
  POST /api/roots  {path, name}       폴더 등록          DELETE /api/roots/<id>  등록 해제
  GET  /api/browse?path=              폴더 탐색 (빈 path → 드라이브/바로가기)
  GET  /api/tree?root=<id>            폴더 트리 (본문 없이 메타만)
  GET  /api/file?root=<id>&path=      파일 하나의 본문
  GET  /api/search?root=<id>&q=       본문 검색
  GET  /raw/<id>/<path>               원본 파일 (iframe, 이미지, 첨부)
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import socket
import string
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as scan  # noqa: E402

VIEWER = scan.VIEWER
HERE = scan.ROOT                      # 보고서 폴더
ROOTS_FILE = HERE / "_roots.json"
LEGACY_ROOTS = VIEWER / "roots.json"  # 1.0 위치
TREE_MAX_FILES = 20000
SEARCH_MAX_FILES = 5000
SEARCH_MAX_HITS = 100
TREE_CACHE_SEC = 2.0
VERSION = scan.VERSION
CONFIG = scan.load_config()

mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/markdown", ".md")


# ---------------------------------------------------------------- roots
class Roots:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items: list[dict] = []
        self.load()

    def load(self) -> None:
        if not ROOTS_FILE.exists() and LEGACY_ROOTS.exists():
            try:
                ROOTS_FILE.write_text(LEGACY_ROOTS.read_text(encoding="utf-8"), encoding="utf-8")
                LEGACY_ROOTS.unlink()
            except OSError:
                pass
        items = []
        if ROOTS_FILE.exists():
            try:
                items = json.loads(ROOTS_FILE.read_text(encoding="utf-8")).get("roots", [])
            except (ValueError, OSError):
                items = []
        items = [r for r in items if r.get("id") != "report" and isinstance(r.get("path"), str)]
        self.items = [{"id": "report", "name": CONFIG.get("title", "Reports"), "path": str(HERE), "default": True}] + items

    def save(self) -> None:
        data = {"roots": [r for r in self.items if not r.get("default")]}
        ROOTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, rid: str) -> dict | None:
        return next((r for r in self.items if r["id"] == rid), None)

    def public(self) -> list[dict]:
        return [{**r, "exists": Path(r["path"]).is_dir()} for r in self.items]

    def add(self, path: str, name: str | None) -> dict:
        p = Path(os.path.expandvars(os.path.expanduser(path.strip()))).resolve()
        if not p.is_dir():
            raise ValueError(f"폴더가 없습니다: {p}")
        with self.lock:
            for r in self.items:
                if Path(r["path"]) == p:
                    return r
            base = re.sub(r"[^A-Za-z0-9가-힣_-]+", "-", (name or p.name or "root")).strip("-").lower() or "root"
            rid, i = base, 2
            while self.get(rid):
                rid, i = f"{base}-{i}", i + 1
            r = {"id": rid, "name": name or p.name or str(p), "path": str(p)}
            self.items.append(r)
            self.save()
            return r

    def remove(self, rid: str) -> bool:
        with self.lock:
            r = self.get(rid)
            if not r or r.get("default"):
                return False
            self.items.remove(r)
            self.save()
            return True


ROOTS = Roots()
_tree_cache: dict[str, tuple[float, dict]] = {}


def safe_join(root_dir: Path, rel: str) -> Path | None:
    """root_dir 안의 rel 경로. 밖으로 나가면 None."""
    rel = rel.replace("\\", "/").strip("/")
    p = (root_dir / rel).resolve() if rel else root_dir.resolve()
    try:
        p.relative_to(root_dir.resolve())
    except ValueError:
        return None
    return p


def get_tree(rid: str) -> dict | None:
    r = ROOTS.get(rid)
    if not r:
        return None
    now = time.time()
    hit = _tree_cache.get(rid)
    if hit and now - hit[0] < TREE_CACHE_SEC:
        return hit[1]
    budget = {"max": TREE_MAX_FILES}
    tree = scan.walk(Path(r["path"]), "", with_body=False, budget=budget, skip_root_files=(rid == "report"))
    tree["name"] = r["name"]
    data = {"generatedAt": scan.iso_time(now), "root": tree, "lazy": True, "rootId": rid,
            "rootName": r["name"], "rootPath": r["path"], "truncated": bool(budget.get("truncated"))}
    _tree_cache[rid] = (now, data)
    return data


def list_drives() -> list[str]:
    if os.name != "nt":
        return ["/"]
    return [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]


def browse(path: str) -> dict:
    if not path:
        return {"path": "", "parent": None, "drives": list_drives(),
                "dirs": [{"name": "🏠 " + Path.home().name, "path": str(Path.home())},
                         {"name": f"📄 {CONFIG.get('title', 'Reports')} (기본)", "path": str(HERE)}]}
    p = Path(os.path.expandvars(os.path.expanduser(path))).resolve()
    if not p.is_dir():
        raise ValueError(f"폴더가 없습니다: {p}")
    dirs = []
    try:
        for ent in sorted(p.iterdir(), key=lambda e: e.name.casefold()):
            try:
                if ent.is_dir() and not ent.name.startswith("$"):
                    dirs.append({"name": ent.name, "path": str(ent), "hidden": scan.is_hidden(ent.name)})
            except OSError:
                continue
    except PermissionError:
        pass
    parent = None if p.parent == p else str(p.parent)
    return {"path": str(p), "parent": parent, "drives": list_drives(), "dirs": dirs}


def search(rid: str, q: str) -> list[dict]:
    r = ROOTS.get(rid)
    if not r or not q:
        return []
    lq = q.casefold()
    hits: list[dict] = []
    tree = get_tree(rid)
    root_dir = Path(r["path"])
    scanned = 0

    def visit(n):
        nonlocal scanned
        if len(hits) >= SEARCH_MAX_HITS or scanned >= SEARCH_MAX_FILES:
            return
        if n["type"] == "dir":
            for c in n["children"]:
                visit(c)
            return
        if n["type"] == "file":
            return
        scanned += 1
        score = 0
        if lq in (n.get("title") or n["name"]).casefold():
            score += 10
        if lq in " ".join(n.get("tags") or []).casefold():
            score += 5
        snippet = ""
        if n["type"] in ("md", "json", "text", "code"):
            p = safe_join(root_dir, n["path"])
            try:
                body = scan.read_text(p, True) if p and p.stat().st_size <= scan.BODY_MAX else ""
            except OSError:
                body = ""
            if n["type"] == "md":
                body = scan.parse_front_matter(body)[1]
            i = body.casefold().find(lq)
            if i >= 0:
                score += 1
                s, e = max(0, i - 70), min(len(body), i + len(q) + 90)
                snippet = ("…" if s > 0 else "") + body[s:e] + ("…" if e < len(body) else "")
        if score:
            hits.append({**{k: n.get(k) for k in ("type", "name", "path", "dir", "ext", "lang", "title", "date", "tags", "size", "mtime")},
                         "score": score, "snippet": snippet})

    if tree:
        visit(tree["root"])
    hits.sort(key=lambda h: (h["score"], h["date"] or "", h["mtime"]), reverse=True)
    return hits


# ---------------------------------------------------------------- http
class Handler(SimpleHTTPRequestHandler):
    server_version = "report-viewer/" + VERSION

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def log_message(self, fmt, *args):
        if os.environ.get("REPORT_VIEWER_LOG"):
            super().log_message(fmt, *args)

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, msg, status=400):
        self.send_json({"error": msg}, status)

    def send_file(self, p: Path):
        try:
            st = p.stat()
            ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(st.st_size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with p.open("rb") as f:
                while chunk := f.read(65536):
                    self.wfile.write(chunk)
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)

    def read_body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return {}

    def do_GET(self):
        u = urlsplit(self.path)
        path = unquote(u.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if path == "/api/ping":
                return self.send_json({"ok": True, "app": "report-viewer", "version": VERSION, "reportDir": str(HERE), "config": CONFIG})
            if path == "/api/roots":
                return self.send_json({"roots": ROOTS.public()})
            if path == "/api/browse":
                return self.send_json(browse(q.get("path", "")))
            if path == "/api/tree":
                data = get_tree(q.get("root", "report"))
                return self.send_json(data) if data else self.send_error_json("unknown root", 404)
            if path == "/api/file":
                r = ROOTS.get(q.get("root", "report"))
                p = r and safe_join(Path(r["path"]), q.get("path", ""))
                if not p or not p.is_file():
                    return self.send_error_json("not found", 404)
                node = scan.file_node(p, q.get("path", "").replace("\\", "/").strip("/"), with_body=True)
                return self.send_json(node or {"error": "unsupported"})
            if path == "/api/search":
                return self.send_json({"hits": search(q.get("root", "report"), q.get("q", "").strip())})
            if path.startswith("/raw/"):
                parts = path[5:].split("/", 1)
                r = ROOTS.get(parts[0])
                p = r and safe_join(Path(r["path"]), parts[1] if len(parts) > 1 else "")
                if not p or not p.is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                return self.send_file(p)
            if path == "/":
                return self.send_file(HERE / "index.html")
            if path.startswith("/_viewer/") or path == "/index.html":
                return super().do_GET()
            p = safe_join(HERE, path)  # 구형 링크 호환: 보고서 폴더의 파일
            if p and p.is_file():
                return self.send_file(p)
            self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as e:
            self.send_error_json(str(e), 400)
        except Exception as e:  # noqa: BLE001
            self.send_error_json(f"{type(e).__name__}: {e}", 500)

    def do_POST(self):
        if urlsplit(self.path).path == "/api/roots":
            body = self.read_body_json()
            try:
                r = ROOTS.add(body.get("path", ""), body.get("name"))
                _tree_cache.pop(r["id"], None)
                return self.send_json({"added": r, "roots": ROOTS.public()})
            except ValueError as e:
                return self.send_error_json(str(e))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        m = re.match(r"^/api/roots/([^/]+)$", urlsplit(self.path).path)
        if m:
            rid = unquote(m.group(1))
            ok = ROOTS.remove(rid)
            _tree_cache.pop(rid, None)
            return self.send_json({"removed": ok, "roots": ROOTS.public()})
        self.send_error(HTTPStatus.NOT_FOUND)


# ---------------------------------------------------------------- main
def already_running(port: int) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == "report-viewer"
    except Exception:  # noqa: BLE001
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def make_server(port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    return httpd


def main() -> None:
    ap = argparse.ArgumentParser(description="보고서 뷰어 로컬 서버")
    ap.add_argument("--port", type=int, default=int(CONFIG.get("port", 8765)))
    ap.add_argument("--no-open", action="store_true", help="브라우저를 자동으로 열지 않음")
    ap.add_argument("--version", action="version", version=f"report-viewer {VERSION}")
    args = ap.parse_args()

    scan.ensure_filetypes_js()
    port = args.port
    if port and already_running(port):
        url = f"http://127.0.0.1:{port}/"
        print(f"이미 실행 중입니다: {url}")
        if not args.no_open:
            webbrowser.open(url)
        return
    while port and not port_free(port):
        port += 1
    httpd = make_server(port)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"{CONFIG.get('title', 'Reports')} 뷰어: {url}   (Ctrl+C 로 종료)", flush=True)
    print(f"기본 폴더: {HERE}", flush=True)
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
