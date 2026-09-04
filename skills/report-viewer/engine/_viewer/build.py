#!/usr/bin/env python3
"""
_viewer/build.py — 보고서 폴더 스캐너 + 색인(data.js) 생성기

    python _viewer/build.py          # 1회 생성 (index.html 을 서버 없이 열 때 필요)
    python _viewer/build.py --watch  # 1초 간격으로 변경을 감시하며 자동 재생성

스캔 규칙(확장자, 제외 폴더, 크기 제한)은 같은 폴더의 filetypes.json 이 단일 원본이다.
브라우저(scan.js)가 쓰는 filetypes.js 도 여기서 생성한다. serve.py 와 hook.py 는 이 모듈을 import 해서 쓴다.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VIEWER = Path(__file__).resolve().parent          # .../report/_viewer
ROOT = VIEWER.parent                              # .../report
OUT = VIEWER / "data.js"
RULES_FILE = VIEWER / "filetypes.json"
RULES_JS = VIEWER / "filetypes.js"
CONFIG_FILE = ROOT / "_config.json"
VERSION = (VIEWER / "VERSION").read_text(encoding="utf-8").strip() if (VIEWER / "VERSION").exists() else "0"

# ---------------------------------------------------------------- 규칙·설정
RULES = json.loads(RULES_FILE.read_text(encoding="utf-8"))
EXT_TYPE: dict[str, str] = {}
for _t, _exts in RULES["types"].items():
    for _e in _exts:
        EXT_TYPE.setdefault(_e, _t)
CODE_EXT: dict[str, str] = RULES["code"]
BODY_MAX: int = RULES["bodyMaxBytes"]
HEAD_BYTES: int = RULES["headBytes"]
HIDDEN_PREFIXES: tuple = tuple(RULES["hiddenPrefixes"])
SKIP_DIR_NAMES = set(RULES["skipDirs"])
SKIP_ROOT_FILES = set(RULES["skipRootFiles"])

DEFAULT_CONFIG = {"title": "Reports", "port": 8765, "categories": {"work": "업무 보고서", "personal": "개인 문서"}, "defaultCategory": "work"}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except ValueError as e:
            print(f"경고: {CONFIG_FILE.name} 을 읽지 못해 기본값을 씁니다 ({e})", file=sys.stderr)
    return cfg


def ensure_filetypes_js() -> None:
    """브라우저용 filetypes.js 를 filetypes.json 에서 만든다 (없거나 오래됐을 때만)."""
    if RULES_JS.exists() and RULES_JS.stat().st_mtime >= RULES_FILE.stat().st_mtime:
        return
    RULES_JS.write_text("// filetypes.json 에서 자동 생성. 직접 수정하지 말 것.\nwindow.REPORT_FILETYPES = "
                        + json.dumps(RULES, ensure_ascii=False) + ";\n", encoding="utf-8")


def is_hidden(name: str) -> bool:
    return name.startswith(HIDDEN_PREFIXES) or name in SKIP_DIR_NAMES


# ---------------------------------------------------------------- 파싱
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.S)
H1_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.M)
DATE_RE = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse_front_matter(text: str) -> tuple[dict, str]:
    """아주 단순한 YAML front matter 파서 (key: value, 배열 [a, b], 리스트 - a). scan.js 와 같은 규칙."""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    last_key = None
    for raw in m.group(1).splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        li = re.match(r"^\s+-\s+(.*)$", line) or re.match(r"^-\s+(.*)$", line)
        if li and last_key:
            if not isinstance(meta.get(last_key), list):
                meta[last_key] = [meta[last_key]] if meta.get(last_key) else []
            meta[last_key].append(unquote(li.group(1)))
            continue
        kv = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if not kv:
            continue
        last_key = kv.group(1)
        v: object = kv.group(2).strip()
        if v.startswith("[") and v.endswith("]"):
            v = [unquote(x) for x in v[1:-1].split(",") if unquote(x)]
        elif v == "true":
            v = True
        elif v == "false":
            v = False
        else:
            v = unquote(v)
        meta[last_key] = v
    return meta, text[m.end():]


def to_date(v) -> str | None:
    if not v:
        return None
    m = DATE_RE.search(str(v))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def iso_time(ts: float) -> str:
    d = datetime.fromtimestamp(ts, timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def read_text(p: Path, full: bool) -> str:
    """UTF-8(BOM 허용)로 읽는다. full=False 면 앞부분(HEAD_BYTES)만."""
    if full:
        return p.read_text(encoding="utf-8-sig", errors="replace")
    with p.open("rb") as f:
        raw = f.read(HEAD_BYTES)
    return raw.decode("utf-8-sig", errors="replace")


# ---------------------------------------------------------------- 노드
def file_node(p: Path, rel: str, with_body: bool = True) -> dict | None:
    """파일 하나를 노드로. with_body=False 면 본문을 빼고 메타만 채운다(서버의 트리 API 용)."""
    ext = p.suffix.lower()
    st = p.stat()
    base = {
        "name": p.name, "path": rel, "dir": rel.rsplit("/", 1)[0] if "/" in rel else "",
        "ext": ext, "size": st.st_size, "mtime": iso_time(st.st_mtime),
    }
    fallback_date = to_date(p.name) or iso_time(st.st_mtime)[:10]
    t = EXT_TYPE.get(ext)
    if t == "md":
        text = read_text(p, with_body).replace("\r\n", "\n")
        meta, body = parse_front_matter(text)
        h1 = H1_RE.search(body)
        title = meta.get("title") or (h1.group(1).strip() if h1 else None) or p.stem
        date = to_date(meta.get("date")) or fallback_date
        tags = meta.get("tags")
        tags = tags if isinstance(tags, list) else ([str(tags)] if tags else [])
        node = {"type": "md", **base, "title": title, "date": date, "tags": tags, "meta": meta}
        if with_body:
            node["body"] = body
        return node
    if t == "html":
        text = read_text(p, False)
        m = TITLE_RE.search(text)
        title = re.sub(r"\s+", " ", m.group(1).strip()) if m else p.stem
        return {"type": "html", **base, "title": title, "date": fallback_date, "tags": []}
    if t == "json" and st.st_size <= BODY_MAX:
        title = p.name
        text = None
        if with_body or st.st_size <= HEAD_BYTES:
            text = read_text(p, True)
            try:
                j = json.loads(text)
                if isinstance(j, dict) and isinstance(j.get("title"), str):
                    title = j["title"]
            except ValueError:
                pass
        node = {"type": "json", **base, "title": title, "date": fallback_date, "tags": []}
        if with_body:
            node["body"] = text
        return node
    if t == "text" and st.st_size <= BODY_MAX:
        node = {"type": "text", **base, "title": p.name, "date": fallback_date, "tags": []}
        if with_body:
            node["body"] = read_text(p, True).replace("\r\n", "\n")
        return node
    if ext in CODE_EXT and st.st_size <= BODY_MAX:
        node = {"type": "code", **base, "title": p.name, "date": fallback_date, "tags": [], "lang": CODE_EXT[ext]}
        if with_body:
            node["body"] = read_text(p, True).replace("\r\n", "\n")
        return node
    if t is not None or ext in CODE_EXT:  # 크기 초과한 json/text/code 와 순수 첨부
        return {"type": "file", **base, "title": p.name, "date": fallback_date, "tags": []}
    return None


def walk(abs_dir: Path, rel_dir: str = "", with_body: bool = True, budget: dict | None = None,
         skip_root_files: bool = True) -> dict:
    """디렉터리 트리. budget={'max': N} 을 주면 파일 N개에서 멈추고 budget['truncated']=True 로 표시한다."""
    children = []
    try:
        entries = list(abs_dir.iterdir())
    except (PermissionError, OSError):
        entries = []
    for ent in entries:
        name = ent.name
        if is_hidden(name):
            continue
        rel = f"{rel_dir}/{name}" if rel_dir else name
        try:
            if ent.is_dir():
                if budget and budget.get("truncated"):
                    break
                children.append(walk(ent, rel, with_body, budget, skip_root_files))
            elif ent.is_file():
                if not rel_dir and skip_root_files and name in SKIP_ROOT_FILES:
                    continue
                if budget is not None:
                    if budget.get("files", 0) >= budget.get("max", 10**9):
                        budget["truncated"] = True
                        break
                    budget["files"] = budget.get("files", 0) + 1
                n = file_node(ent, rel, with_body)
                if n:
                    children.append(n)
        except (PermissionError, OSError):
            continue
    children.sort(key=lambda n: (n["type"] != "dir", n["name"].casefold()))
    return {"type": "dir", "name": rel_dir.rsplit("/", 1)[-1] if rel_dir else "", "path": rel_dir, "children": children}


def stats(root: dict) -> dict:
    s = {"md": 0, "html": 0, "json": 0, "text": 0, "code": 0, "file": 0, "dir": -1}

    def count(n):
        s[n["type"]] += 1
        if n["type"] == "dir":
            for c in n["children"]:
                count(c)
    count(root)
    return s


# ---------------------------------------------------------------- 빌드
def build(quiet: bool = False) -> dict:
    ensure_filetypes_js()
    cfg = load_config()
    root = walk(ROOT)
    s = stats(root)
    data = {"generatedAt": iso_time(time.time()), "version": VERSION, "config": cfg, "root": root}
    js = ("// 자동 생성 파일. 직접 수정하지 말고 `python _viewer/build.py` 를 실행하세요.\n"
          "window.REPORT_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    OUT.write_text(js, encoding="utf-8")
    if not quiet:
        t = time.strftime("%H:%M:%S")
        print(f"[{t}] data.js 생성: md {s['md']}, html {s['html']}, json {s['json']}, txt {s['text']}, code {s['code']}, "
              f"첨부 {s['file']}, 폴더 {s['dir']}")
    return s


def snapshot() -> dict:
    snap = {}
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT).as_posix()
        if any(is_hidden(part) for part in rel.split("/")):
            continue
        if p.is_file():
            st = p.stat()
            snap[rel] = (st.st_mtime_ns, st.st_size)
        else:
            snap[rel] = None
    return snap


def main() -> None:
    build()
    if "--watch" not in sys.argv:
        return
    print("변경 감시 중... (Ctrl+C 로 종료)")
    prev = snapshot()
    try:
        while True:
            time.sleep(1)
            cur = snapshot()
            if cur != prev:
                prev = cur
                try:
                    build()
                except Exception as e:  # noqa: BLE001
                    print(e, file=sys.stderr)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
