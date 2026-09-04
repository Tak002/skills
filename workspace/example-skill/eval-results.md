# example-skill 평가 결과

문제지: `evals.json` (1문제, 기준 3개). 실행: `python workspace/run_evals.py --skill example-skill`.

## 기록

| iteration | 날짜 | with-skill | baseline | delta | 메모 |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-04 | 3/3 (100%) | 1/3 (33%) | +66.7 | 격리 실행(빈 임시 폴더 + 스킬 사본). 실행기 검증용 |

## 발견과 조치

- 실행기를 완성하는 동안 세 번 잘못된 결과가 나왔고 전부 실행기 문제였다 (모두 고침):
  1. `--disallowedTools` 가 가변 옵션이라 뒤따르는 프롬프트 단어를 도구 이름으로 삼킴 → 프롬프트를 stdin 으로.
  2. Windows 의 `claude.cmd` 셔틀이 argv 를 첫 줄바꿈에서 자름 → 마찬가지로 stdin 으로. 채점관 claude 가 이 원인을 정확히 진단해 줬다.
  3. 저장소 루트에서 돌리니 baseline claude 가 `skills/` 를 스스로 찾아 읽어 with-skill 과 같은 점수(3/3 vs 3/3) → 빈 임시 폴더에서 실행. 그러자 `claude -p` 가 작업 폴더 밖의 SKILL.md 읽기를 거부해 with-skill 이 0/3 → 스킬 폴더를 임시 폴더 안으로 복사.
- 최종: baseline 은 "예시라서 실제 작업을 하지 않는다", "AGENTS.md" 를 말하지 못했고, with-skill 은 셋 다 말했다. 예시 스킬치고는 기대대로.
