# 설계 배경

## 왜 이 방식인가

- 브라우저는 `file://` 로 연 페이지가 다른 파일을 읽거나 폴더 목록을 보는 것을 막는다. 그래서 정적 뷰어는 (1) 빌드가 만든 색인(`data.js`)을 읽거나 (2) 사용자가 폴더를 골라 권한을 주는(File System Access API) 두 통로만 쓸 수 있다.
- 색인은 파일이 바뀔 때마다 다시 만들어야 하므로 불편하다. 그래서 작은 Python 서버(`serve.py`)를 두어 폴더를 직접 읽게 했다. 서버 모드에서는 색인이 필요 없고, PC 의 어떤 폴더든 등록해 볼 수 있다.
- 세 방식이 공존하는 이유: 서버 모드가 기본이지만, Python 이 없는 환경이나 파일을 그냥 더블클릭해 보고 싶을 때를 위해 정적 모드를 남겼다. Claude Code 훅이 색인을 자동으로 만들어 주므로 정적 모드도 대부분 손이 가지 않는다.

## 렌더링 방식 비교 (검토 기록)

| 선택지 | 판단 |
|---|---|
| **marked + github-markdown-css + highlight.js + mermaid + KaTeX** | 채택. 설치·서버 없이 가장 가볍고, 모두 로컬에 두어 오프라인 동작. |
| markdown-it | 플러그인이 가장 많다. 각주·컨테이너 같은 확장이 필요해지면 교체 후보. |
| remark/rehype | AST 파이프라인. 브라우저 단독 사용에는 무겁다. |
| Docsify | 빌드 없이 md 를 렌더링하지만 `fetch` 를 쓰므로 `file://` 에서 안 열린다. 로컬 서버를 띄운다면 대안. |
| MkDocs Material, VitePress, Docusaurus | 문서 사이트로는 최고. 빌드와 프로젝트 셋업이 커서 보고서 폴더에는 과하다. |
| Pandoc | md 한 편을 HTML/PDF/DOCX 로 바꿀 때 최강. 폴더 탐색 뷰어는 따로 필요. |
| VS Code 미리보기, Obsidian, Typora, 브라우저 확장, 단일 HTML 뷰어 | 편집기·단일 파일 용도. 폴더를 링크로 오가는 뷰어로는 부족. |

## 규칙의 단일 원본

스캔 규칙(확장자 → 타입, 코드 언어, 제외 폴더, 크기 제한)은 `engine/_viewer/filetypes.json` 하나다. `build.py` 가 읽고, 브라우저용 `filetypes.js` 를 거기서 생성해 `scan.js` 가 읽는다. front matter 파싱 같은 로직은 Python 과 JS 에 각각 있으므로 `tests/test_scan.py` 의 동등성 테스트로 같은 결과를 보장한다.

## 보안

- 서버는 127.0.0.1 에만 바인딩한다. 등록한 폴더 밖의 경로는 거부한다.
- 등록한 폴더의 html 은 `sandbox` iframe 으로 표시해 뷰어의 출처(서버 API)에 접근하지 못하게 한다.
- md 는 DOMPurify 로 정화한다. mermaid 는 `securityLevel: loose` 인데, 다이어그램 안의 클릭 링크를 허용하기 위해서다. 신뢰할 수 없는 문서를 볼 폴더라면 `strict` 로 바꾼다.
