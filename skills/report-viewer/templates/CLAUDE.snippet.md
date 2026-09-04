<!-- report-viewer:begin (setup.py 가 관리하는 구간. 직접 고치지 말고 _config.json 을 바꾼 뒤 setup.py 를 다시 실행) -->
## 보고서는 `{{DEST}}/` 안에 작성한다 (report-viewer {{VERSION}})

보고서, 정리 문서, 분석 결과, 회의록 등 "읽는 용도의 산출물"은 반드시 `{{DEST}}/` 아래에 `.md`(기본) 또는 `.html` 로 저장한다. 구조화된 결과는 `.json`, 로그·원문은 `.txt`/`.log`, 첨부 코드는 원래 확장자 그대로 함께 두어도 된다 (뷰어가 각각 트리, 줄 번호 텍스트, 하이라이트로 보여 준다). 다른 곳에 만들지 않는다.

### 어디에 넣나
{{CATEGORY_LIST}}
- 어느 쪽인지 애매하면 사용자에게 묻지 말고 `{{DEST}}/{{DEFAULT_CATEGORY}}/` 에 두고, 응답에서 위치를 알려 준다. 필요하면 그 아래에 프로젝트별 하위 폴더를 만든다.

### 파일 규칙
- 파일명: `YYYY-MM-DD-주제.md` (공백 대신 `-`)
- 맨 위에 front matter 를 넣고, 본문 첫 줄은 `# 제목` (title 과 같게):
  ```yaml
  ---
  title: 보고서 제목
  date: {{TODAY}}
  tags: [태그1, 태그2]
  ---
  ```
- 코드 블록은 언어를 지정한다. 다이어그램은 ```` ```mermaid ````, 수식은 `$$ $$` 또는 `\( \)` (인라인 `$…$` 를 쓰려면 front matter 에 `math: true`).
- 다른 문서는 상대 경로로 링크한다 (`[지난 주](./2026-08-26-weekly.md)`). 이미지는 같은 폴더에 두고 상대 경로로 넣는다.
- html 로 만들 때는 CSS/JS 를 인라인한 단일 파일로 만든다.
- 초안·임시 파일은 `_` 로 시작하는 이름을 쓰면 뷰어에서 제외된다.

### 보는 방법 (사용자에게 안내할 내용)
- `{{DEST}}/start.cmd`(Windows) 또는 `{{DEST}}/start.sh` 를 실행하면 로컬 서버가 뜨고 브라우저가 열린다. 새 파일은 새로고침만 하면 보인다. 링크 형식: `http://127.0.0.1:{{PORT}}/#/~report/<경로>`.
- 서버 없이 `{{DEST}}/index.html` 을 더블클릭해도 열린다. 이때는 색인(`_viewer/data.js`)이 필요한데, Claude Code 훅이 Write/Edit 때마다 자동으로 다시 만든다. 훅이 돌지 않은 것 같으면(응답에 "report 색인 갱신" 이 없으면) `python {{DEST}}/_viewer/build.py` 를 실행한다. Bash 로 파일을 복사·이동한 뒤에도 같다.
- 뷰어 내부(`{{DEST}}/_viewer/`, `index.html`, `start.*`)는 report-viewer 스킬이 관리한다. 손대지 말고, 바꾸려면 스킬 쪽을 고친 뒤 `setup.py` 로 다시 설치한다. `_config.json`, `_roots.json` 은 사용자 설정이다.
<!-- report-viewer:end -->
