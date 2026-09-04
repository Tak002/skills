# notion-export 참고

## 1. 왜 notion-client + notion-x-to-md 인가

2026-09 기준으로 확인한 도구들. 기준은 (a) 남의 공개 페이지를 토큰 없이 읽는가, (b) 인라인 DB 의 행 페이지까지 따라가는가, (c) Markdown 품질, (d) 유지보수 상태.

| 도구 | API | 토큰 | DB 행 | 비고 |
| --- | --- | --- | --- | --- |
| **notion-client + notion-x-to-md** (NotionX/react-notion-x) | 비공식 v3 | 공개 페이지는 불필요, 비공개는 `token_v2` | `getPage` 가 컬렉션 쿼리까지 받아옴 | 8.0.8 (2026-09-03). 블록 종류·컬렉션 지원이 가장 넓다. 재귀는 직접 구현 (이 스킬의 `export.mjs`). |
| notion-to-md, notion-exporter(py), notion4ever, notion2markdown, notion-cli | 공식 API | 통합 토큰 + 페이지를 통합에 **공유**해야 함 | 지원 | 남의 공개 페이지(notion.site)는 공유 권한을 줄 수 없어 **불가**. 내 워크스페이스 백업에는 좋다. |
| notion-exporter (GitHub Action, Go) | 내부 export API | `token_v2` | 지원 | 유지보수 종료 선언. 워크스페이스 내부 페이지용. |
| AshikNesin/notion-crawler | 비공식 v3 | 불필요 | 부분 | 오래됨, 블록 → md 변환 없음 (Next.js 스타터에서 떼어냄). |
| notion-page-scraper (marcopiii) | 공식 API | 필요 | DB 내부 페이지 미지원 | 소규모. |
| Nikok97/notion_scraper, Apify Notion Scraper | Playwright 렌더링 | 불필요 | 링크 따라감 | 느리고(페이지당 브라우저 렌더), Apify 는 유료(페이지당 $0.004). 렌더 HTML 을 파싱하므로 블록 구조가 무너진다. |
| notion-scraper (PyPI) | ? | ? | ? | 2021 이후 갱신 없음. |
| kjk/notionapi (Go) | 비공식 v3 | 공개 불필요 | tomarkdown 있음 | Go 툴체인 필요. |

결론: 공개 페이지·비공개 페이지·DB 행을 한 코드로 다루려면 비공식 v3 API 가 필요하고, 그 위에서 가장 잘 관리되는 변환기가 `notion-x-to-md` 다.

### 검증 기록 (2026-09-04)

- 대상: `rare-antelope-f3b.notion.site/974e07b1...` (공개, "[스마트리뷰어] 매뉴얼"). 루트 아래 인라인 DB 11개, 행 51개, 자식 페이지 2개 = 총 57 페이지.
- `npx -y notion-x-to-md <url>` 로 루트 361줄 변환 확인. DB 는 행 제목만 표로 나오고 링크가 없어서 `export.mjs` 가 "## 하위 페이지" 트리와 상대 링크를 덧붙인다.
- 이름 없는 인라인 DB(콜아웃 안에 넣은 표)는 `collection.name` 이 비어 있다. 페이지 안에서 그 블록을 `#앵커`로 가리키는 링크 글자(목차) → 감싸는 콜아웃/토글 제목 → 앞 형제 헤딩 순으로 이름을 추정한다 (`contextName`).
- **토글형 제목**(`header`/`sub_header`/`sub_sub_header` 에 자식이 달린 것)의 자식을 notion-x-to-md 8.0.8 이 통째로 버린다. 이 매뉴얼은 본문 대부분이 그 안에 있어서 처음 결과가 제목만 남았다. 변환 직전에 자식을 부모 목록으로 끌어올리는 `flattenToggleHeadings` 로 해결. 결과: 이미지 107장 → 252장.
- 링크 정규식이 `)` 에서 끊겨 `..._(5).png` 같은 URL 이 잘렸다. 괄호 한 겹을 허용하도록 수정.
- 동영상·첨부 파일(`prod-files-secure.s3...`)은 서명 없는 URL 로 나와 내려받지 못한다. 링크만 남는다.

### 알려진 한계와 보완 (2026-09-04, 비공개 워크스페이스 59 페이지 표본 감사)

재현은 `scripts/audit.mjs <url> <out.json>`. 감사에서 찾은 것과 export.mjs 의 보완 상태:

| 발견 | 보완 (export.mjs) | 남은 것 |
| --- | --- | --- |
| DB 행의 속성값(select·status·date·relation…)이 저장되지 않음 (116개 중 9개) | `renderProps`: 컬렉션 스키마로 `\| 속성 \| 값 \|` 표를 `# 제목` 아래에 넣음 (`--no-props`) | person 은 `‣` 로 남을 수 있음 (사용자 레코드가 응답에 없을 때) |
| `tab` 블록 아래 내용이 통째로 빠짐 (루트 29블록) | `flattenTabs`: 탭을 펼치고 라벨을 `###` 제목으로 | 없음 |
| 스키마 없는 컬렉션(GitHub 연동 DB)에서 변환이 통째로 실패 | `patchSchemalessCollections`: 빈 스키마 주입. 그래도 실패하면 DB 뷰를 빼고 재시도, 마지막에 stub | 그 DB 는 이름만 남음 |
| 범위 밖 페이지 링크가 `/32hex` 로 깨짐 | 1차 `normalizeLinks` → `https://www.notion.so/<id>`, 마지막 패스 `relativizeLinks` 로 범위 안은 상대 경로 | 앵커(#블록)는 버림 |
| 굵게 공백 `** **`, `**제목 **다음` | `fixEmphasis` (코드 펜스 밖) | 중첩·교차 서식은 못 고침 |
| 표 셀 안 줄바꿈이 행을 쪼갬 | `fixTableRows`: `\|` 로 끝나지 않는 표 줄을 다음 줄과 합침 | |
| 파일·동영상·PDF 미다운로드 | `downloadFiles`: `signed_urls[blockId]` 로 받아 `assets/`. `--max-file-mb`(기본 100) | **비공개 첨부는 `token_v2` 만으로는 403** (S3 가 Notion 오류 페이지를 돌려줌). `file_token` 쿠키(첨부를 브라우저에서 한 번 열면 생김)가 필요해 `get-token.mjs --open` 으로 받는다. `/image/` 프록시는 이미지 전용(422). 서명 실패(500) 페이지는 링크만 |
| 순차 처리·재개·상한·필터 없음 | `--concurrency`(기본 2), `--resume`(manifest `.notion-export.json`, 수정 시각 비교), `--max-pages`, `--exclude` | |
| DB 표는 첫 뷰 기준, 보드·캘린더·갤러리도 표. 보드 뷰 쿼리 400 | 행 수집은 모든 뷰 결과 합집합 + parent 가 collection 인 블록 예비 | 그룹·필터·정렬 정보 없음. 보드 뷰만 있는 DB 는 행 누락 가능 |
| 아이콘·표지·수정 시각·댓글 미저장 | front matter 에 `icon`(이모지), `last_edited` 추가 | 표지·댓글·작성자 |
| DB 999행 초과 절단(미검증), 경로 260자 초과 위험 | | 그대로 |

## 2. 비공개 페이지 인증: 브라우저에서 어떻게 가져오나

Notion 웹은 로그인 세션을 `token_v2` 쿠키(httpOnly, 도메인 `.notion.so`)와 `notion_user_id` 쿠키로 유지한다. 비공식 API 는 이 두 값을 `Cookie: token_v2=...`, `x-notion-active-user-header: <user_id>` 로 보내면 브라우저와 같은 권한으로 읽는다. 문제는 "브라우저 안의 httpOnly 쿠키를 어떻게 프로그램이 꺼내느냐"다.

| 방식 | 동작 여부 (Windows, 2026) | 설명 |
| --- | --- | --- |
| **A. DevTools Protocol `Storage.getCookies`** (이 스킬의 `get-token.mjs`) | **동작** | 브라우저를 `--remote-debugging-port` + 전용 `--user-data-dir` 로 띄우고 CDP 로 쿠키를 읽는다. httpOnly 도 나온다. Chrome 136+ 는 **기본 프로필**에서 원격 디버깅을 막았으므로 전용 프로필이 필수이고, 그래서 처음 한 번은 그 프로필에서 로그인해야 한다. 이후는 프로필에 세션이 남아 자동. 의존성 없음 (Node 22 내장 WebSocket). 주의: 브라우저를 `kill` 로 끄면 쿠키가 디스크에 안 남아 다음에 다시 로그인해야 한다. `Browser.close` 로 정상 종료한다. 첨부 다운로드용 `file_token` 은 첨부를 한 번 열어야 생긴다 (`--open`). |
| B. 쿠키 DB 파일 복호화 (browser_cookie3, pycookiecheat, yt-dlp `--cookies-from-browser`) | Chrome/Edge **불가**, Firefox 가능 | Chrome 127(2024-07)부터 App-Bound Encryption: 쿠키 키가 SYSTEM 권한 서비스에 묶여 있어 사용자 프로세스가 DPAPI 로 못 푼다. Edge 도 같은 엔진. browser_cookie3 이슈들이 "Unable to get key for cookie decryption" 으로 열려 있다. Firefox 는 `cookies.sqlite` 가 평문이라 여전히 읽힌다. |
| C. Playwright persistent context | 동작 | A 와 같은 원리(전용 프로필)를 Playwright 가 감싼 것. `context.cookies()` 로 읽음. Playwright + 브라우저 바이너리 설치가 필요해서 A 보다 무겁다. |
| D. 수동 복사 | 동작 | 브라우저 F12 → Application → Cookies → `www.notion.so` → `token_v2` 값 복사 → `NOTION_TOKEN_V2` 환경 변수 또는 `--token`. 가장 단순하고 어떤 환경에서도 된다. 스크립트가 막히면 이걸로. |
| E. 공식 API 통합 토큰 | 동작(조건부) | 내 워크스페이스 페이지에 한해 통합을 만들고 페이지를 공유하면 공식 API 로 읽을 수 있다. 남의 공개 페이지에는 쓸 수 없다. |

주의:
- `token_v2` 는 로그아웃 전까지 유효하고 쉽게 무효화하기 어렵다. 파일에 두면 `.env`(gitignore) 에만, 응답이나 로그에 찍지 않는다.
- 회사 PC 의 SSO 로 로그인하는 워크스페이스도 로그인 뒤에는 같은 `token_v2` 쿠키를 쓰므로 A/D 가 그대로 통한다.
- 이 저장소 환경에는 `chrome-devtools` MCP 가 있지만 쿠키를 읽는 툴이 없다 (`evaluate_script` 는 httpOnly 를 못 본다). 그래서 별도 스크립트로 만들었다.

## 3. API 메모

- 엔드포인트: `POST https://www.notion.so/api/v3/loadPageChunk` (블록 트리), `queryCollection` (DB 행), `syncRecordValues`, `getSignedFileUrls`. `notion-client` 의 `getPage(id)` 가 이들을 묶어 `recordMap`(`block`, `collection`, `collection_view`, `collection_query`)으로 준다.
- 응답 레코드는 `{value: Block}` 또는 `{value: {value: Block, role}}` 두 형태가 섞여 온다. `export.mjs` 의 `rec()` 가 둘 다 푼다.
- 하위 페이지 판별: 부모 페이지의 `content` 를 따라 내려가다 `type: "page"` 블록을 만나면 자식 페이지. 다른 페이지로의 링크는 `alias` 타입이라 구분된다. `collection_view`/`collection_view_page` 는 `collection_id`(연결 DB 는 `format.collection_pointer.id`)로 컬렉션을 찾고, `collection_query[collectionId][viewId].*.blockIds` 가 행 페이지 id 다.
- `notionPageToMarkdown(recordMap)` 은 옵션이 없다 (8.0.x). 이미지는 `https://app.notion.com/image/...` 서명 URL 로 나오고, 내부 링크는 `/32hex?pvs=..#anchor` 형태다. 후처리는 `export.mjs` 의 `rewriteLinks`, `downloadImages`.
