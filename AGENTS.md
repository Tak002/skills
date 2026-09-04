# AGENTS.md

이 저장소는 Agent Skills 모음이다. 여기서 작업하는 에이전트는 아래 규칙을 따른다.

## 저장소 규칙

- 스킬은 `skills/<name>/SKILL.md` 에만 둔다. 다른 위치에 SKILL.md 를 만들지 않는다.
- 폴더 이름과 front matter 의 `name` 은 같아야 하고, 소문자·숫자·하이픈만 쓴다 (kebab-case, 64자 이하).
- `description` 은 필수이며 1024자 이하. "무엇을 하는지" 와 "언제 쓰는지(트리거 문구)" 를 함께 적는다. 에이전트는 본문을 읽기 전에 description 만으로 스킬을 고르므로 여기가 가장 중요하다.
- 본문은 실행 절차 중심으로 짧게. 배경 설명·표·긴 예시는 같은 폴더의 `reference.md`, `examples/`, `scripts/` 로 분리하고 SKILL.md 에서 상대 경로로 가리킨다.
- 스크립트를 포함할 때는 언어와 실행 방법을 SKILL.md 에 명시한다. 외부 의존성은 최소화한다.
- 절대 경로(`C:\Users\...`)를 SKILL.md 에 넣지 않는다. 스킬 폴더 기준 상대 경로만 쓴다.
- 비밀값(토큰·비밀번호·개인 이메일)을 커밋하지 않는다.

## 스킬을 추가·수정한 뒤

1. `python scripts/validate.py` 실행. 실패하면 고친다.
2. `README.md` 의 스킬 목록 표를 갱신한다.
3. 동작이 바뀌었으면 `CHANGELOG.md` 에 한 줄 추가한다.

## 파일 역할

| 경로 | 역할 |
| --- | --- |
| `skills/` | 배포 대상 스킬 |
| `templates/SKILL.md` | 새 스킬 시작점 |
| `scripts/validate.py` | 형식 검사. CI 와 로컬에서 동일하게 실행 |
| `.claude-plugin/plugin.json` | Claude Code 플러그인 메타데이터 |
| `.claude-plugin/marketplace.json` | `/plugin marketplace add` 용 마켓플레이스 정의 |
