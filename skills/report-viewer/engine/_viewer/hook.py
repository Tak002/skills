#!/usr/bin/env python3
"""
Claude Code PostToolUse 훅: Write/Edit 로 보고서 폴더 안의 파일이 바뀌면 색인(data.js)을 다시 만든다.
setup.py 가 이 파일을 <project>/.claude/hooks/report-build.py 로 복사하고 settings.json 에 등록한다.

    python report-build.py <보고서 폴더(프로젝트 기준 상대경로)>

stdin 으로 훅 입력 JSON 을 받는다. 보고서 폴더 밖이거나 _viewer/ 등 내부 파일이면 아무것도 하지 않는다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    sys.dont_write_bytecode = True
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    report = (project / (sys.argv[1] if len(sys.argv) > 1 else "report")).resolve()
    try:
        j = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return
    file = (j.get("tool_response") or {}).get("filePath") or (j.get("tool_input") or {}).get("file_path") or ""
    if not file:
        return
    abs_path = (project / file).resolve()
    try:
        rel = abs_path.relative_to(report)
    except ValueError:
        return  # 보고서 폴더 밖
    if not rel.parts or rel.parts[0].startswith(("_", ".")):
        return  # _viewer/, _config.json 등 내부 파일
    build = report / "_viewer" / "build.py"
    if not build.exists():
        return
    r = subprocess.run([sys.executable, str(build)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.stderr.write(r.stderr or r.stdout)
        return  # 훅 실패로 작업을 막지는 않는다
    sys.stdout.write(json.dumps({"systemMessage": f"report 색인 갱신: {rel.as_posix()}"}))


if __name__ == "__main__":
    main()
