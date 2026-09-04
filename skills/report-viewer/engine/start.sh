#!/usr/bin/env bash
# 보고서 뷰어 서버 시작 (mac/Linux). 브라우저가 자동으로 열립니다. Ctrl+C 로 종료.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 _viewer/serve.py "$@"; fi
if command -v python >/dev/null 2>&1; then exec python _viewer/serve.py "$@"; fi
echo "Python 3 을 찾지 못했습니다. https://www.python.org/downloads/ 에서 설치하세요." >&2
exit 1
