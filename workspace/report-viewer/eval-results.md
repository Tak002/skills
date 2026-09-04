# report-viewer 평가 결과

문제지: `evals.json` (3문제, 기준 10개). 실행: `python workspace/run_evals.py --skill report-viewer`.

## 기록

| iteration | 날짜 | with-skill | baseline | delta | 메모 |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-04 | 10/10 (100%) | 0/10 (0%) | +100.0 | 격리 실행(설정별 작업 폴더). 문제별 4/4·3/3·3/3 vs 0/4·0/3·0/3 |

## 발견과 조치

- 격리 전 실행에서는 10/10 vs 10/10 이 나왔다. baseline claude 가 같은 임시 폴더에 놓인 with-skill 용 스킬 사본을 Glob 으로 찾아 읽은 것 (응답에 setup.py, start.cmd, build.py 가 18번 등장). 설정마다 작업 폴더를 분리한 뒤 baseline 이 0/10 으로 떨어졌다. **평가 환경의 격리가 스킬 문장보다 먼저 검증할 대상**이라는 교훈.
- baseline 은 세 문제 모두에서 이 스킬 고유의 이름(setup.py, `--dest`, start.cmd, `_viewer/build.py`, `.claude/settings.json` 훅)을 하나도 말하지 못하고 Vite/React 로 뷰어를 새로 만들자거나 `git mv` 를 제안했다. 이 스킬은 "설치 절차와 파일 이름을 정확히 아는 것" 이 가치의 전부다.
- with-skill 은 만점이라 이번 문제지로는 더 고칠 곳이 안 보인다. 다음 문제 후보: 이미 설치된 프로젝트에서 업그레이드 요청, `_config.json` 의 분류 폴더 변경, 포트 충돌.
