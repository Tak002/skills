# notion-export 평가 결과

문제지: `evals.json` (3문제, 기준 12개). 실행: `python workspace/run_evals.py --skill notion-export`.

## 기록

| iteration | 날짜 | with-skill | baseline | delta | 메모 |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-04 | 11/12 (91.7%) | 2/12 (16.7%) | +75.0 | 격리 실행. 문제별 4/4·3/4·4/4 vs 2/4·0/4·0/4 |
| 2 | 2026-09-04 | 4/4 (100%, 문제 2만) | 0/4 | +100.0 | SKILL.md 5단계에 원리 설명 지시 추가 후 `--test 2`. 기준 2 통과 |

## 발견과 조치

- **iteration 1, 문제 2 (비공개 페이지) 기준 2 FAIL**: with-skill 응답이 "전용 프로필로 Chrome 창이 뜬다" 고만 하고, 쿠키 DB 직접 읽기(browser_cookie3)가 Chrome/Edge 에서 안 되는 이유나 DevTools Protocol 방식을 설명하지 않았다. SKILL.md 5단계에 그 내용이 있지만 "사용자에게 설명하라" 는 지시가 없어서 Claude 가 절차만 말했다. → SKILL.md 5단계에 "안내할 때 원리 한 줄 포함" 지시 추가.
- baseline 이 통과한 2칸은 공개 페이지 문제의 기준 3·4 ("토큰 불필요", "이미지·링크 처리 언급"). 일반 지식으로도 답할 수 있는 기준이라 변별력이 낮다. 다음에 기준을 고칠 때 후보.
- baseline 은 세 문제 모두에서 이 저장소의 스크립트(export.mjs, get-token.mjs)와 옵션(--exclude, --resume, --prefix)을 전혀 언급하지 못했다. 스킬의 가치는 "절차와 옵션 이름을 정확히 아는 것" 에 있다.
- 응답 시간: with-skill 78~100초, baseline 85~116초. 스킬을 읽는 비용보다 baseline 이 대안을 탐색하는 비용이 컸다.
