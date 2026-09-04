# workspace — 스킬 평가 작업장

스킬을 만들거나 고칠 때 "정말 나아졌는가" 를 숫자로 확인하는 곳이다. 사용자에게 배포되지 않는다. 배포 대상은 `skills/` 뿐이다.

```text
workspace/
├─ run_evals.py          공용 실행·채점기 (스킬마다 복사하지 않는다)
├─ test_run_evals.py     실행기 자체의 unittest (claude 는 가짜로 대체)
├─ README.md             이 문서
└─ <skill-name>/         스킬 하나당 폴더 하나. 이름은 skills/<skill-name> 과 같게
   ├─ evals.json         문제지: 요청 + 합격 기준. 형식은 ../templates/evals.json
   ├─ eval-results.md    사람이 정리한 결과와 다음에 고칠 점
   └─ iteration-N/       실행 결과 (git 에 올리지 않음)
      ├─ summary.txt  config.json
      └─ <test-name>/<config>/outputs/response.md, timing.json, grading.txt, grading.json
```

## 흐름

```mermaid
flowchart LR
  E[evals.json] --> R[run_evals.py]
  R --> A["claude -p  (스킬 읽고 답하라)"]
  R --> B["claude -p  (질문만)"]
  A --> J[claude -p 채점: PASS|n|근거]
  B --> J
  J --> S[iteration-N/summary.txt]
  S --> M[eval-results.md 에 정리]
  M -. 고칠 점 .-> K[skills/x/SKILL.md]
  K -. 다시 .-> R
```

1. `evals.json` 에 실제 사용자가 할 법한 요청 3개쯤과, 각 요청마다 검증 가능한 기준 3~4개를 적는다. 기준은 "X 를 언급한다", "Y 를 하지 않는다" 처럼 채점관이 근거를 댈 수 있는 문장으로.
2. `python workspace/run_evals.py --skill <name>` 을 돌린다. 요청마다 claude 를 두 번(스킬 있음/없음) 부르고, 응답을 채점관 claude 에 보내 기준별 PASS/FAIL 을 받는다.
3. `iteration-N/summary.txt` 의 합격률과 delta 를 본다. `grading.txt` 의 근거를 읽고 FAIL 이 스킬 문장 때문인지 채점 오류인지 가른다.
4. 발견을 `eval-results.md` 에 적고 SKILL.md 를 고친다. 고친 뒤 `--a 이전 --b 이후` 로 두 버전을 직접 비교할 수도 있다.

## 명령

```powershell
python workspace/run_evals.py --skill notion-export                 # 전체
python workspace/run_evals.py --skill notion-export --test 2        # 한 문제
python workspace/run_evals.py --skill notion-export --grade-only    # 마지막 iteration 재채점
python workspace/run_evals.py --skill notion-export --with-skill-only
python workspace/run_evals.py --skill notion-export --a skills/notion-export/SKILL.md --b C:/tmp/SKILL.md --a-label old --b-label new
python workspace/run_evals.py --skill notion-export --dry-run       # 프롬프트만 확인, claude 호출 없음
python -m unittest discover -s workspace -q                         # 실행기 테스트 (표준 라이브러리만)
```

옵션: `--model`, `--judge-model`, `--timeout`(호출당 초), `--claude-arg <인자>`(반복 가능), `--allow-actions`.

## 규칙

- 평가 대상 claude 는 **저장소 밖의 빈 임시 폴더**에서 돈다 (`--cwd` 로 바꿀 수 있음). 저장소 루트에서 돌리면 baseline claude 가 `skills/` 를 스스로 찾아 읽어 with-skill 과 같은 답을 내고, 비교가 무의미해진다 (첫 실행에서 실제로 11/12 vs 11/12 가 나왔다).
- with-skill 설정의 스킬 폴더는 그 임시 폴더 안으로 **복사**해서 준다 (`node_modules`, `.env` 제외). `claude -p` 는 작업 폴더 밖 파일 읽기를 자동 거부하므로 저장소 경로를 직접 가리키면 못 읽는다 (두 번째 실행에서 실제로 0/3 이 나왔다).
- 작업 폴더는 **설정마다 따로** 둔다 (`<임시>/with-skill/`, `<임시>/baseline/`, `<임시>/judge/`). 한 폴더를 같이 쓰면 baseline claude 가 옆의 스킬 사본을 Glob 으로 찾아 읽는다 (세 번째 실행에서 report-viewer 가 10/10 vs 10/10).
- 평가 대상 claude 에는 기본으로 `--disallowedTools Bash,Write,Edit` 를 준다. 스킬이 스크립트를 "실행" 하는 대신 "무엇을 실행하겠다" 고 답하는지를 본다. 실제 실행까지 보려면 `--allow-actions` (네트워크·파일에 영향 줄 수 있으니 주의).
- 채점관도 claude 다. 근거 없이 PASS 만 있으면 의심한다. 기준을 더 구체적으로 쓰는 것이 채점관을 바꾸는 것보다 낫다.
- 문제 3개면 기준 12칸 정도다. 1칸 차이로 결론 내리지 말고, 같은 버전을 두 번 돌려 흔들림을 본 뒤 판단한다.
- `iteration-N/` 은 지우지 않는다. 과거 점수와 비교하는 자료다 (git 에는 안 올라감).
- 프롬프트에 토큰·개인정보를 넣지 않는다. `response.md` 가 로컬에 남는다.
