# vendor 라이브러리 목록

뷰어가 오프라인에서 동작하도록 함께 배포하는 서드파티 파일이다. 버전은 파일 머리글·내부 `version` 필드에서 확인한 값이며, 2026-09-02 에 jsDelivr(npm) 에서 받았다. 갱신할 때는 아래 URL 의 버전을 올리고 이 표를 함께 고친다.

| 파일 | 라이브러리 | 버전 | 라이선스 | 출처 |
|---|---|---|---|---|
| `marked.min.js` | marked | 15.0.12 | MIT | https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js |
| `marked-gfm-heading-id.umd.js` | marked-gfm-heading-id | 4.x (파일 안에 버전 표기 없음) | MIT | https://cdn.jsdelivr.net/npm/marked-gfm-heading-id/lib/index.umd.js |
| `highlight.min.js` | highlight.js | 11.12.0 | BSD-3-Clause | https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.12.0/highlight.min.js |
| `github.min.css`, `github-dark.min.css` | highlight.js 테마 | 11.12.0 | BSD-3-Clause | https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.12.0/styles/ |
| `github-markdown-light.min.css`, `github-markdown-dark.min.css` | github-markdown-css | 5.9.0 | MIT | https://cdn.jsdelivr.net/npm/github-markdown-css@5.9.0/ |
| `mermaid.min.js` | mermaid | 11.17.2 | MIT | https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js |
| `katex.min.js`, `katex.min.css`, `fonts/*.woff2` (20개) | KaTeX | 0.16.47 | MIT | https://cdn.jsdelivr.net/npm/katex@0.16.47/dist/ |
| `auto-render.min.js` | KaTeX auto-render (contrib) | 0.16.47 | MIT | https://cdn.jsdelivr.net/npm/katex@0.16.47/dist/contrib/auto-render.min.js |
| `purify.min.js` | DOMPurify | 3.4.14 | Apache-2.0 OR MPL-2.0 | https://cdn.jsdelivr.net/npm/dompurify@3.4.14/dist/purify.min.js |

- 전체 크기는 약 4 MB 이고 대부분이 mermaid 다. 다이어그램이 필요 없으면 `mermaid.min.js` 를 빼고 `index.html` 의 script 태그를 지우면 된다.
- 모두 permissive 라이선스라 그대로 재배포할 수 있다. 각 라이선스 전문은 위 출처의 저장소에 있다.
