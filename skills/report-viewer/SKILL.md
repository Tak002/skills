---
name: report-viewer
description: 프로젝트에 보고서 폴더(위치는 사용자가 정함, 기본 report/)와 정적/서버 겸용 뷰어(md·html·json·txt·코드)를 설치하고, Claude 가 보고서를 그 폴더의 규칙대로 쓰게 한다. "보고서 뷰어 설치", "report 폴더 만들어", "보고서 보는 페이지", 보고서 폴더 위치 변경, 뷰어 업그레이드·문제 해결 요청에 사용.
---

# report-viewer

프로젝트 안에 `report/`(이름은 바꿀 수 있음) 폴더를 만들고, 그 안의 md·html·json·txt·코드 파일을 브라우저에서 예쁘게 보는 뷰어를 설치한다. 뷰어는 두 방식으로 동작한다.

- **서버 모드(권장)**: `report/start.cmd` 또는 `start.sh` 를 실행하면 Python 로컬 서버가 뜨고 브라우저가 열린다. 색인이 필요 없고, PC 의 다른 폴더도 등록해 볼 수 있다.
- **정적 모드**: `report/index.html` 을 더블클릭. 색인 파일(`_viewer/data.js`)이 필요하며 Claude Code 훅이 자동으로 만든다.

요구 사항: Python 3.10 이상. 외부 패키지는 쓰지 않는다. 렌더링 라이브러리는 스킬 안에 들어 있어 오프라인에서 동작한다.

## 설치 (처음 또는 업그레이드)

### 1. 위치를 정한다

설치 전에 아래 두 가지를 확정한다. 사용자의 요청에 이미 들어 있으면 묻지 않고, 없으면 기본값을 제시하며 한 번만 묻는다.

| 항목 | 옵션 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 프로젝트 루트 | `--project-dir` | 현재 폴더 | `CLAUDE.md` 와 `.claude/settings.json`(훅)이 여기에 만들어진다. 보통 Claude Code 를 연 폴더. |
| 보고서 폴더 | `--dest` | `report` | 프로젝트 루트 기준 상대 경로. 예: `docs/reports`, `notes`, `산출물`. 이 이름이 CLAUDE.md 규칙과 훅에 그대로 들어간다. |

선택 사항: 뷰어 제목 `--title "팀 보고서"`. 분류 폴더(기본 `work/`, `personal/`)를 바꾸려면 설치 후 `<dest>/_config.json` 의 `categories` 를 고치고 setup.py 를 다시 실행한다.

이미 설치된 프로젝트(CLAUDE.md 에 `<!-- report-viewer:begin` 구간이 있음)에서는 그 구간에 적힌 폴더 이름을 `--dest` 로 그대로 쓴다. 업그레이드 때 위치를 다시 묻지 않는다.

### 2. setup.py 를 실행한다

`<skill>` 은 이 SKILL.md 가 있는 폴더다. 설치 방식에 따라 다르므로 스킬이 로드된 실제 경로를 쓴다. 프로젝트 설치면 `.claude/skills/report-viewer`, 전역 설치면 `~/.claude/skills/report-viewer`, 플러그인이면 플러그인 캐시 안이다. 여러 번 실행해도 안전하다 (엔진 파일만 교체하고 사용자 문서·설정은 보존).

```bash
python <skill>/scripts/setup.py                                   # ./report 에 설치
python <skill>/scripts/setup.py --dest docs/reports --title "팀 보고서"
python <skill>/scripts/setup.py --project-dir ../other-project    # 다른 프로젝트에 설치
python <skill>/scripts/setup.py --no-hook                         # 훅 등록 생략
```

setup.py 가 하는 일:
1. `<dest>/_viewer/`, `index.html`, `start.cmd`, `start.sh` 를 스킬의 `engine/` 으로 교체한다.
2. `<dest>/_config.json`, `README.md`, 분류 폴더(기본 `work/`, `personal/`)가 없으면 만든다. 샘플 문서 하나를 넣는다.
3. `.claude/hooks/report-build.py` 를 복사하고 `.claude/settings.json` 의 PostToolUse 훅(Write|Edit)에 등록한다. 훅 명령에는 setup 을 실행한 Python 의 절대 경로를 쓴다.
4. 프로젝트 `CLAUDE.md` 의 `<!-- report-viewer:begin -->` … `end` 구간을 템플릿으로 갱신한다 (없으면 끝에 붙인다).
5. 색인을 한 번 생성한다.

### 3. 사용자에게 안내한다

- 보고서 폴더 위치(`<dest>/`)와, 그 안의 분류 폴더.
- `<dest>/start.cmd`(Windows) 또는 `start.sh` 를 더블클릭하면 뷰어가 열린다.
- 앞으로 Claude 가 만드는 보고서는 자동으로 `<dest>/` 규칙을 따른다 (CLAUDE.md 에 들어감).

## Claude 가 보고서를 쓸 때

설치 후 프로젝트 CLAUDE.md 에 들어간 규칙을 따른다. 요약:
- 위치: `<dest>/<분류>/YYYY-MM-DD-주제.md`. 분류가 애매하면 기본 분류(`_config.json` 의 `defaultCategory`)에 두고 위치를 알려 준다.
- front matter(`title`, `date`, `tags`)와 `# 제목` 첫 줄. 코드 블록 언어 지정, `mermaid`, `$$` 수식, 상대 경로 링크.
- html 은 단일 파일. json/txt/log/코드도 그대로 두면 뷰어가 보여 준다.
- 저장하면 훅이 색인을 갱신한다. 응답에 "report 색인 갱신" 이 없으면 `python <dest>/_viewer/build.py`.

## 구조

```text
report-viewer/
├─ SKILL.md
├─ engine/                 설치 시 통째로 복사되는 뷰어 본체 (사용자 폴더의 _viewer/, index.html, start.*)
│  ├─ index.html  start.cmd  start.sh
│  └─ _viewer/  app.js  app.css  scan.js  build.py  serve.py  hook.py  filetypes.json  VERSION  vendor/ (버전·라이선스 목록은 vendor/VERSIONS.md)
├─ templates/              처음 설치 때만 만드는 사용자 파일: _config.json  README.md  sample.md  CLAUDE.snippet.md
├─ scripts/setup.py        설치·업그레이드
├─ tests/                  python -m unittest discover -s <skill>/tests
└─ docs/                   설계 배경, 렌더링 방식 비교
```

- 스캔 규칙(확장자, 제외 폴더, 크기 제한)은 `engine/_viewer/filetypes.json` 하나가 원본이다. Python(`build.py`)과 브라우저(`scan.js`, `build.py` 가 만드는 `filetypes.js` 를 읽음)가 같은 규칙을 쓴다.
- 사용자 설정은 `<dest>/_config.json` (title, port, categories, defaultCategory). 등록한 폴더 목록은 `<dest>/_roots.json`.
- 서버 API: `/api/ping /api/roots /api/browse /api/tree /api/file /api/search /raw/<root>/<path>`. 127.0.0.1 에만 바인딩.

## 문제 해결

- 보고서 폴더 위치를 바꾸고 싶다 → 기존 폴더를 새 위치로 옮긴(또는 이름을 바꾼) 뒤 `setup.py --dest <새 경로>` 를 실행한다. 훅과 CLAUDE.md 구간이 새 경로로 갱신된다. 옮기지 않고 실행하면 새 폴더가 하나 더 생기니 주의한다.
- 훅이 안 돈다 → `.claude/settings.json` 의 명령에 적힌 Python 경로가 유효한지 확인. `/hooks` 로 설정을 다시 읽거나 세션을 재시작. 수동: `python <dest>/_viewer/build.py`.
- `start.cmd` 가 Python 을 못 찾는다 → PATH 에 python 이 없다. `py -3 <dest>/_viewer/serve.py` 로 직접 실행.
- `start.cmd` 를 더블클릭하면 "'xxx' is not recognized" 가 줄줄이 뜬다 → 파일에 비 ASCII 문자가 들어갔다. cmd.exe 는 배치 파일을 OEM 코드 페이지로 읽으므로 `engine/start.cmd` 는 주석·메시지까지 ASCII 만 쓴다 (한글 금지). 서버가 뜨기까지 Python 기동 시간 때문에 몇 초 걸릴 수 있다.
- 포트 충돌 → `_config.json` 의 `port` 를 바꾸거나 `serve.py --port 9000`. 이미 떠 있으면 새로 띄우지 않고 브라우저만 연다.
- 뷰어를 고쳤다 → 스킬의 `engine/` 을 고치고 `setup.py` 를 다시 실행한다. 사용자 폴더의 `_viewer/` 를 직접 고치면 다음 업그레이드에서 사라진다.
- 스캔 규칙을 바꿨다 → `filetypes.json` 만 고친다. front matter 파싱 같은 로직을 바꾸면 `build.py` 와 `scan.js` 를 함께 고치고 `tests/` 의 동등성 테스트를 돌린다.
