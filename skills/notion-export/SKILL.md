---
name: notion-export
description: Notion 페이지 하나를 하위 페이지와 인라인 데이터베이스 행까지 재귀적으로 따라가 Markdown 파일 트리(폴더 = 하위 페이지/DB, 이미지는 assets/)로 저장한다. 공개(notion.site) 페이지는 토큰 없이, 비공개 페이지는 브라우저에서 꺼낸 로그인 쿠키(token_v2)로 읽는다. "노션 페이지 긁어줘/스크래핑/추출/백업", "notion 하위 페이지까지 markdown 으로", "notion.site 링크를 md 로 저장", "노션 매뉴얼을 report 에 정리" 같은 요청에 사용.
---

# notion-export

Notion 페이지 URL 을 받아 그 페이지와 그 안의 모든 하위 페이지, 인라인 DB 의 각 행 페이지를 Markdown 으로 저장한다. 폴더 구조가 Notion 의 계층을 그대로 따른다.

```text
<out>/
├─ <prefix>루트-제목.md            루트 페이지 (끝에 "## 하위 페이지" 트리 색인)
├─ 하위-페이지-A.md
├─ 하위-페이지-A/                  A 가 또 자식을 가지면 같은 이름의 폴더
├─ DB-이름/                        인라인 데이터베이스 = 폴더, 행 = 파일
│  ├─ <prefix>행-제목.md
│  └─ ...
└─ assets/                         내려받은 이미지 (Notion 서명 URL 은 곧 만료되므로 기본으로 내려받음)
```

- Notion 내부 링크(`/32hex`, `notion.so/...`)는 저장된 파일 사이의 상대 경로로 바꾼다.
- 각 파일 맨 위에 front matter(`title`, `date`, `tags`, `source`, `notion_id`)와 `# 제목` 을 넣는다 (report-viewer 규칙과 호환).
- 요구 사항: Node 22 이상. 처음 한 번 `scripts/` 에서 `npm install` (notion-client, notion-x-to-md).

## 실행 절차

`<skill>` 은 이 SKILL.md 가 있는 폴더의 실제 경로다.

1. **입력 확인.** URL(또는 32자리 id)과 출력 폴더를 정한다. 보고서로 남기는 것이면 프로젝트의 `report/` 규칙(`report/work/<프로젝트>/<주제>/`, 파일명 접두어 `YYYY-MM-DD-`)을 따르고 `--prefix` 로 날짜를 준다.

2. **의존성 설치 (처음 한 번).**

   ```powershell
   Set-Location <skill>/scripts; npm install --no-audit --no-fund
   ```

3. **트리 미리보기.** 페이지 수와 구조를 먼저 본다. 수십 페이지가 넘으면 사용자에게 알리고 진행한다.

   ```powershell
   node <skill>/scripts/export.mjs <url> --list
   ```

4. **추출.**

   ```powershell
   node <skill>/scripts/export.mjs <url> --out <폴더> --prefix 2026-09-04- --tags notion,manual
   ```

   옵션: `--exclude "백업|Legacy"`(제목이 맞는 하위 페이지·DB 건너뜀), `--max-pages N`, `--resume`(중단 재개·증분: `<out>/.notion-export.json` 에 기록된 페이지 중 수정 시각이 같은 것은 다시 받지 않음), `--concurrency N`(기본 2), `--depth N`(기본 10), `--delay ms`(기본 300), `--no-images`, `--no-files`(파일·동영상·PDF 안 받음), `--max-file-mb N`(기본 100), `--no-props`(DB 행 속성 표 생략), `--no-frontmatter`.

   큰 페이지(수백 행 DB)는 먼저 `--list` 로 규모를 보고, 백업 사본 같은 것은 `--exclude` 로 빼고, `--max-pages` 로 끊어 받다가 `--resume` 으로 이어 받는다.

5. **비공개 페이지면** 3·4 단계에서 `Could not find block` / 401 / 403 으로 실패한다. 브라우저 로그인 쿠키를 꺼내 `.env` 에 저장한 뒤 다시 실행한다.

   ```powershell
   node <skill>/scripts/get-token.mjs --write          # Chrome 창이 뜬다 → Notion 로그인 → 자동으로 닫힘
   node <skill>/scripts/get-token.mjs --browser edge --write
   ```

   - 전용 프로필(`~/.cache/notion-export/profile-<browser>`)을 원격 디버깅 포트로 띄우고 DevTools Protocol 로 httpOnly 쿠키 `token_v2`, `notion_user_id` 를 읽는다. 로그인은 프로필에 남아 다음부터는 창이 잠깐 떴다 닫힌다.
   - 사용자에게 안내할 때는 왜 창이 뜨는지 한 줄로 설명한다: "브라우저 쿠키 파일을 직접 읽는 방식은 Chrome/Edge 의 App-Bound Encryption 때문에 동작하지 않아서, 전용 프로필 창을 띄우고 DevTools Protocol 로 로그인 쿠키를 읽습니다."
   - 결과는 `<skill>/scripts/.env` (gitignore 대상). `export.mjs` 가 자동으로 읽는다. 환경 변수 `NOTION_TOKEN_V2`, `NOTION_USER_ID` 또는 `--token`, `--user` 로 줘도 된다.
   - **비공개 첨부(파일·동영상·PDF)까지 받으려면** `file_token` 쿠키가 더 필요하다. 로그인만으로는 안 생기고 첨부를 한 번 열어야 생긴다:

     ```powershell
     node <skill>/scripts/get-token.mjs --open <첨부가 있는 페이지 URL> --timeout 600 --write   # 창에서 파일 하나 클릭 → 자동 저장
     ```

     없으면 export 가 `파일 실패 (HTTP 403 ...) — file_token 쿠키 없음` 을 찍고 본문·이미지는 정상 저장한다.
   - 쿠키 DB 파일을 직접 읽는 방식(browser_cookie3 등)은 Chrome/Edge 127+ 의 App-Bound Encryption 때문에 Windows 에서 동작하지 않는다. 이유와 대안은 [reference.md](reference.md).

6. **보고.** 저장 위치, 페이지 수, 이미지 수, 실패한 페이지(있으면)를 알린다. `report/` 안에 넣었으면 Claude 훅이 돌지 않으므로 `python report/_viewer/build.py` 를 실행해 색인을 갱신한다.

## 주의

- `token_v2` 는 비밀번호와 같다. 커밋·공유·응답 본문에 노출하지 않는다. `.env` 는 이 폴더의 `.gitignore` 에 이미 들어 있다.
- 비공식 API(`/api/v3`)를 쓴다. Notion 이 형식을 바꾸면 `notion-client` 를 올려야 한다 (`npm update` 후 재실행).
- 이미지 URL 은 서명이 붙어 있어 수십 분 뒤 만료된다. `--no-images` 를 쓰면 문서의 이미지가 곧 깨진다.
- 토글형 제목과 탭(`tab`) 아래 내용은 제목 바로 뒤에 펼쳐서 저장한다 (변환기가 둘 다 버리기 때문). 탭 라벨은 `###` 제목이 된다.
- DB 행 페이지는 `# 제목` 바로 아래에 `| 속성 | 값 |` 표로 속성값(select·status·date·relation 등)을 넣는다. 사람(person) 속성은 `‣` 로 남을 수 있다.
- 파일·동영상·PDF 는 서명 URL 로 내려받아 `assets/` 에 둔다 (비공개 페이지는 로그인 쿠키를 함께 보냄). 실패하면 서명 URL(곧 만료)이 남는다.
- 추출 범위 밖 페이지로의 링크는 `https://www.notion.so/<id>` 로 남긴다. 범위 안이면 상대 경로.
- 링크 블록(다른 페이지를 가리키는 alias)은 따라가지 않는다. 그 페이지 안에 실제로 들어 있는 하위 페이지와 DB 행만 재귀한다.
- 같은 페이지가 여러 곳에서 참조되면 한 번만 저장하고 나머지는 링크로 연결한다.

## 참고

- [reference.md](reference.md): 도구 비교(왜 notion-client + notion-x-to-md 인가), 인증 방식 4가지 비교, API 메모.
- `scripts/export.mjs`, `scripts/get-token.mjs`: 둘 다 `--help`.
- `scripts/audit.mjs <url> <out.json> [DB당 행수=2] [제외 정규식=백업]`: 큰 페이지를 통째로 받기 전에 표본으로 블록 종류·손실·속성 보존을 점검한다. 알려진 한계 목록은 `reference.md` 1절.
