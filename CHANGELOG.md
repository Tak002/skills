# Changelog

## 0.2.0 - 2026-09-04

- `report-viewer` 1.1.0 추가: 보고서 폴더 + 뷰어 설치 스킬 (`scripts/setup.py`, `engine/`, `tests/`).
- `report-viewer` SKILL.md: 설치 명령을 스킬 폴더 기준 경로(`<skill>/scripts/setup.py`)로 바꿔 플러그인 설치에서도 동작하게 함. 설치 전에 보고서 폴더 위치(`--dest`)와 프로젝트 루트(`--project-dir`)를 정하는 절차와 위치 변경 방법 추가.

## 0.1.0 - 2026-09-04

- 저장소 틀 생성: `skills/`, `templates/`, `scripts/validate.py`, 플러그인 메타데이터, CI.
- `example-skill` 예시 추가.
