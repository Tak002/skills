#!/usr/bin/env python3
"""
report-viewer 설치·업그레이드 스크립트. 프로젝트 루트에서 실행한다. 여러 번 실행해도 같은 결과가 나온다.

    python .claude/skills/report-viewer/scripts/setup.py [--dest report] [--title "Reports"] [--project-dir .]
                                                          [--no-hook] [--no-claude-md] [--no-sample] [--no-build]

- 엔진(<dest>/_viewer, index.html, start.*)은 항상 스킬의 engine/ 으로 교체한다.
- 사용자 파일(_config.json, README.md, 분류 폴더, 문서, _roots.json)은 없을 때만 만들고 있으면 건드리지 않는다.
- .claude/settings.json 의 PostToolUse 훅과 CLAUDE.md 의 report-viewer 구간을 갱신한다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ENGINE = SKILL / "engine"
TEMPLATES = SKILL / "templates"
BEGIN, END = "<!-- report-viewer:begin", "<!-- report-viewer:end -->"


def log(msg: str) -> None:
    print("  " + msg)


def fill(text: str, vars: dict) -> str:
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def install_engine(dest: Path) -> None:
    viewer = dest / "_viewer"
    # 1.0 위치의 사용자 데이터를 옮긴다
    legacy_roots = viewer / "roots.json"
    if legacy_roots.exists() and not (dest / "_roots.json").exists():
        shutil.move(str(legacy_roots), str(dest / "_roots.json"))
        log("_viewer/roots.json → _roots.json 으로 이동")
    if viewer.exists():
        shutil.rmtree(viewer)
    shutil.copytree(ENGINE / "_viewer", viewer, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data.js", "filetypes.js"))
    for name in ("index.html", "start.cmd", "start.sh"):
        shutil.copy2(ENGINE / name, dest / name)
    try:
        (dest / "start.sh").chmod(0o755)
    except OSError:
        pass
    # 1.0 에서 루트에 있던 엔진 파일 정리
    for legacy in ("build.py", "build.mjs", "serve.py"):
        p = dest / legacy
        if p.exists() and ("report" in p.read_text(encoding="utf-8", errors="replace")[:2000]):
            p.unlink()
            log(f"구버전 파일 삭제: {legacy}")
    shutil.rmtree(dest / "__pycache__", ignore_errors=True)
    log(f"엔진 설치: {viewer.relative_to(dest.parent)} (v{(ENGINE / '_viewer' / 'VERSION').read_text().strip()})")


def ensure_user_files(dest: Path, title: str | None, with_sample: bool) -> dict:
    cfg_path = dest / "_config.json"
    if not cfg_path.exists():
        cfg = json.loads((TEMPLATES / "_config.json").read_text(encoding="utf-8"))
        if title:
            cfg["title"] = title
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log("_config.json 생성")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if title and cfg.get("title") != title:
        cfg["title"] = title
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"_config.json title → {title}")
    cats: dict = cfg.get("categories") or {}
    vars = {
        "TITLE": cfg.get("title", "Reports"), "TODAY": date.today().isoformat(), "PORT": cfg.get("port", 8765),
        "DEFAULT_CATEGORY": cfg.get("defaultCategory") or (next(iter(cats)) if cats else ""),
        "CATEGORY_LIST": "\n".join(f"- `{k}/` → {v}" for k, v in cats.items()) or "- (분류 없음: 루트에 바로 둔다)",
    }
    for k in cats:
        (dest / k).mkdir(parents=True, exist_ok=True)
    readme = dest / "README.md"
    if not readme.exists():
        readme.write_text(fill((TEMPLATES / "README.md").read_text(encoding="utf-8"), vars), encoding="utf-8")
        log("README.md 생성")
    if with_sample:
        has_doc = any(p.suffix.lower() in (".md", ".html") and p.name.lower() != "readme.md"
                      for p in dest.rglob("*") if p.is_file() and not any(s.startswith(("_", ".")) for s in p.relative_to(dest).parts))
        if not has_doc:
            target_dir = dest / vars["DEFAULT_CATEGORY"] if vars["DEFAULT_CATEGORY"] else dest
            target_dir.mkdir(parents=True, exist_ok=True)
            sample = target_dir / f"{vars['TODAY']}-viewer-sample.md"
            sample.write_text(fill((TEMPLATES / "sample.md").read_text(encoding="utf-8"), vars), encoding="utf-8")
            log(f"샘플 문서 생성: {sample.relative_to(dest)}")
    return vars


def install_hook(project: Path, dest_rel: str) -> None:
    hooks_dir = project / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ENGINE / "_viewer" / "hook.py", hooks_dir / "report-build.py")
    for legacy in ("report-build.mjs",):
        if (hooks_dir / legacy).exists():
            (hooks_dir / legacy).unlink()
            log(f"구버전 훅 삭제: {legacy}")
    settings_path = project / ".claude" / "settings.json"
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except ValueError as e:
            sys.exit(f"오류: {settings_path} 가 올바른 JSON 이 아닙니다 ({e}). 고친 뒤 다시 실행하세요.")
    py = Path(sys.executable).resolve().as_posix()
    command = f'"{py}" "$CLAUDE_PROJECT_DIR/.claude/hooks/report-build.py" "{dest_rel}"'
    entry = {"type": "command", "command": command, "timeout": 30, "statusMessage": "report 색인 갱신 중..."}
    post = settings.setdefault("hooks", {}).setdefault("PostToolUse", [])
    # 기존 report-build 훅 제거 후 추가
    for group in post:
        group["hooks"] = [h for h in group.get("hooks", []) if "report-build" not in str(h.get("command", ""))]
    post[:] = [g for g in post if g.get("hooks")]
    post.append({"matcher": "Write|Edit|MultiEdit", "hooks": [entry]})
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"훅 등록: .claude/settings.json (PostToolUse Write|Edit → {py})")


def update_claude_md(project: Path, dest_rel: str, vars: dict) -> None:
    snippet = fill((TEMPLATES / "CLAUDE.snippet.md").read_text(encoding="utf-8"),
                   {**vars, "DEST": dest_rel, "VERSION": (ENGINE / "_viewer" / "VERSION").read_text().strip()}).rstrip() + "\n"
    path = project / "CLAUDE.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if BEGIN in text and END in text:
        s, e = text.index(BEGIN), text.index(END) + len(END)
        text = text[:s] + snippet.rstrip() + text[e:]
        log("CLAUDE.md 의 report-viewer 구간 갱신")
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + snippet
        log("CLAUDE.md 에 report-viewer 구간 추가")
    path.write_text(text, encoding="utf-8")


def run_build(dest: Path) -> None:
    import importlib.util
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("report_build", dest / "_viewer" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    s = mod.build(quiet=True)
    log(f"색인 생성: md {s['md']}, html {s['html']}, json {s['json']}, txt {s['text']}, code {s['code']}, 첨부 {s['file']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="report-viewer 설치/업그레이드")
    ap.add_argument("--dest", default="report", help="보고서 폴더 (프로젝트 기준 상대경로, 기본 report)")
    ap.add_argument("--project-dir", default=".", help="프로젝트 루트 (기본 현재 폴더)")
    ap.add_argument("--title", help="뷰어 제목 (_config.json 의 title)")
    ap.add_argument("--no-hook", action="store_true")
    ap.add_argument("--no-claude-md", action="store_true")
    ap.add_argument("--no-sample", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()

    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 이상이 필요합니다.")
    project = Path(args.project_dir).resolve()
    dest_rel = args.dest.replace("\\", "/").strip("/")
    dest = (project / dest_rel).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    print(f"report-viewer 설치 → {dest}")
    install_engine(dest)
    vars = ensure_user_files(dest, args.title, not args.no_sample)
    if not args.no_hook:
        install_hook(project, dest_rel)
    if not args.no_claude_md:
        update_claude_md(project, dest_rel, vars)
    if not args.no_build:
        run_build(dest)
    print(f"완료. {dest_rel}/start.cmd (또는 start.sh) 를 실행하면 뷰어가 열립니다.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
