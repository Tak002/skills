# Changelog

## 0.3.0 - 2026-09-04

- `notion-export` 추가: Notion 페이지를 하위 페이지·인라인 DB 행까지 재귀적으로 Markdown 트리로 저장 (`scripts/export.mjs`, notion-client + notion-x-to-md). 비공개 페이지용으로 브라우저 DevTools Protocol 에서 `token_v2` 를 읽는 `scripts/get-token.mjs` 포함. 도구·인증 방식 비교는 `reference.md`.
- `notion-export`: 표본 감사 스크립트 `scripts/audit.mjs` 와 알려진 한계 목록(`reference.md` 1절) 추가. 비공개 워크스페이스 59 페이지 감사 결과: DB 행 속성 미저장, `tab` 블록 손실, 스키마 없는 컬렉션에서 변환 실패 등.
- `notion-export` export.mjs 개정: DB 행 속성 표(사람 속성은 getRecordValues 로 이름 해석), `tab` 블록 펼침, 스키마 없는 컬렉션 폴백, 범위 밖 링크를 Notion URL 로, 굵게 공백·표 셀 줄바꿈 정리, 파일·동영상 서명 다운로드(`--no-files`, `--max-file-mb`), `--exclude`/`--max-pages`/`--resume`/`--concurrency`. 페이지를 받는 즉시 저장하고 마지막에 링크·트리를 한 번 더 훑는 구조로 변경.
- `notion-export` get-token.mjs: 기본 브라우저 Chrome, `Browser.close` 로 정상 종료(쿠키 보존), `file_token` 쿠키 저장(`--open`), `--show`.

## 0.2.0 - 2026-09-04

- `report-viewer` 1.1.0 추가: 보고서 폴더 + 뷰어 설치 스킬 (`scripts/setup.py`, `engine/`, `tests/`).
- `report-viewer` SKILL.md: 설치 명령을 스킬 폴더 기준 경로(`<skill>/scripts/setup.py`)로 바꿔 플러그인 설치에서도 동작하게 함. 설치 전에 보고서 폴더 위치(`--dest`)와 프로젝트 루트(`--project-dir`)를 정하는 절차와 위치 변경 방법 추가.

## 0.1.0 - 2026-09-04

- 저장소 틀 생성: `skills/`, `templates/`, `scripts/validate.py`, 플러그인 메타데이터, CI.
- `example-skill` 예시 추가.
