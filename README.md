# skills

Tak002 의 개인 Agent Skills 저장소. Claude Code(및 SKILL.md 규격을 읽는 다른 에이전트)에서 쓰는 스킬을 한 곳에서 관리하고 배포한다.

## 구조

```
skills/                 배포되는 스킬. 폴더 하나 = 스킬 하나, 안에 SKILL.md 필수
  example-skill/        틀을 보여 주는 예시 스킬 (실제 기능 없음)
templates/              새 스킬을 만들 때 복사하는 SKILL.md, evals.json 템플릿
workspace/              스킬 평가 작업장 (배포 안 됨). run_evals.py + <skill>/evals.json, eval-results.md
scripts/validate.py     SKILL.md 형식 + workspace/<skill>/evals.json 검사 (CI 에서도 실행)
.claude-plugin/         Claude Code 플러그인/마켓플레이스 메타데이터
.github/workflows/      PR·push 때 validate.py 실행
AGENTS.md / CLAUDE.md   이 저장소에서 에이전트가 지킬 규칙
```

## 설치

### Claude Code 플러그인으로 (자동 갱신, 읽기 전용)

```
/plugin marketplace add Tak002/skills
/plugin install tak002-skills@tak002-skills
```

### 파일로 복사해서 (직접 고쳐 쓰는 용도)

```
npx skills@latest add Tak002/skills
```

특정 스킬만 고르려면:

```
npx skills@latest add Tak002/skills --skill example-skill
```

### 수동

`skills/<이름>/` 폴더를 통째로 `~/.claude/skills/` (전역) 또는 프로젝트의 `.claude/skills/` 에 복사한다.

## 스킬 목록

| 이름 | 설명 |
| --- | --- |
| [example-skill](skills/example-skill/SKILL.md) | 스킬 작성 틀을 보여 주는 예시. 실제 기능은 없다. |
| [report-viewer](skills/report-viewer/SKILL.md) | 프로젝트에 `report/` 폴더와 md·html·json·txt·코드 뷰어(서버/정적 겸용)를 설치하고, Claude 가 보고서를 그 폴더 규칙대로 쓰게 한다. Python 3.10+, 외부 패키지 없음. |
| [notion-export](skills/notion-export/SKILL.md) | Notion 페이지를 하위 페이지·인라인 DB 행(속성 표 포함)·이미지·첨부까지 재귀적으로 Markdown 파일 트리로 저장한다. 공개 페이지는 토큰 없이, 비공개 페이지는 브라우저(Chrome/Edge)에서 DevTools Protocol 로 꺼낸 `token_v2` 로. `--exclude`/`--max-pages`/`--resume` 지원. Node 22+, `npm install` 필요. |

## 새 스킬 추가

1. `templates/SKILL.md` 를 `skills/<kebab-case-이름>/SKILL.md` 로 복사한다.
2. front matter 의 `name` 을 폴더 이름과 같게 맞추고, `description` 에 "무엇을 하는지 + 언제 쓰는지" 를 한 문단으로 적는다. 에이전트는 이 description 만 보고 스킬을 고른다.
3. 본문에는 실행 절차를 적는다. 긴 참고 자료는 같은 폴더의 `reference.md`, `examples/` 로 뺀다.
4. `templates/evals.json` 을 `workspace/<이름>/evals.json` 으로 복사해 요청 3개와 합격 기준을 적는다.
5. `python scripts/validate.py` 를 돌려 통과하는지 확인한다.
6. `python workspace/run_evals.py --skill <이름>` 으로 스킬 있음/없음을 비교하고 결과를 `workspace/<이름>/eval-results.md` 에 적는다. 자세한 흐름은 [workspace/README.md](workspace/README.md).
7. 이 README 의 스킬 목록 표에 한 줄 추가한다.

자세한 작성 규칙은 [AGENTS.md](AGENTS.md) 에 있다.

## 라이선스

MIT
