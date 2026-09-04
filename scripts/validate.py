"""skills/*/SKILL.md 형식 검사 + workspace/<skill>/evals.json 존재·형식 검사.

사용법:  python scripts/validate.py
종료 코드: 문제가 하나라도 있으면 1, 없으면 0.
표준 라이브러리만 쓴다 (PyYAML 불필요).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
WORKSPACE_DIR = ROOT / "workspace"
sys.path.insert(0, str(WORKSPACE_DIR))
try:
    from run_evals import validate_evals  # workspace/run_evals.py
except Exception:  # noqa: BLE001
    validate_evals = None
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESC = 1024


def parse_front_matter(text: str) -> tuple[dict[str, str] | None, str]:
    """맨 위 --- ... --- 블록을 key: value 사전으로 읽는다. 없으면 (None, 이유)."""
    if not text.startswith("---"):
        return None, "front matter 가 파일 맨 위에 없다"
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, "front matter 닫는 --- 가 없다"
    data: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line or line.startswith((" ", "\t")):
            continue  # 중첩 값은 검사 대상이 아니다
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip().strip("'\"")
    return data, ""


def check_skill(folder: Path) -> list[str]:
    errors: list[str] = []
    skill_md = folder / "SKILL.md"
    if not skill_md.is_file():
        return [f"{folder.name}: SKILL.md 가 없다"]

    text = skill_md.read_text(encoding="utf-8")
    fm, why = parse_front_matter(text)
    if fm is None:
        return [f"{folder.name}: {why}"]

    name = fm.get("name", "")
    desc = fm.get("description", "")

    if not name:
        errors.append(f"{folder.name}: name 이 없다")
    else:
        if name != folder.name:
            errors.append(f"{folder.name}: name '{name}' 이 폴더 이름과 다르다")
        if not NAME_RE.match(name):
            errors.append(f"{folder.name}: name 은 kebab-case 여야 한다 ('{name}')")
        if len(name) > MAX_NAME:
            errors.append(f"{folder.name}: name 이 {MAX_NAME}자를 넘는다")

    if not desc:
        errors.append(f"{folder.name}: description 이 없다")
    elif len(desc) > MAX_DESC:
        errors.append(f"{folder.name}: description 이 {MAX_DESC}자를 넘는다 ({len(desc)}자)")

    body = text.split("---", 2)[-1] if fm is not None else ""
    if not body.strip():
        errors.append(f"{folder.name}: front matter 아래 본문이 비어 있다")

    if re.search(r"[A-Za-z]:\\Users\\", text):
        errors.append(f"{folder.name}: 절대 경로(C:\\Users\\...)가 들어 있다")

    errors.extend(check_evals(folder.name))
    return errors


def check_evals(name: str) -> list[str]:
    """workspace/<name>/evals.json 이 있고 형식이 맞는지."""
    path = WORKSPACE_DIR / name / "evals.json"
    if not path.is_file():
        return [f"{name}: workspace/{name}/evals.json 이 없다 (templates/evals.json 을 복사해 만든다)"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"{name}: workspace/{name}/evals.json 이 JSON 이 아니다 ({e})"]
    if validate_evals is None:
        return [f"{name}: workspace/run_evals.py 를 불러오지 못해 evals.json 을 검사할 수 없다"]
    return [f"{name}: evals.json — {p}" for p in validate_evals(data, name)]


def main() -> int:
    if not SKILLS_DIR.is_dir():
        print(f"skills/ 폴더가 없다: {SKILLS_DIR}")
        return 1

    folders = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    if not folders:
        print("검사할 스킬이 없다")
        return 1

    all_errors: list[str] = []
    for folder in folders:
        errs = check_skill(folder)
        status = "FAIL" if errs else "ok  "
        print(f"[{status}] {folder.name}")
        all_errors.extend(errs)

    if all_errors:
        print()
        for e in all_errors:
            print(f"  - {e}")
        print(f"\n{len(all_errors)}개 문제")
        return 1

    print(f"\n{len(folders)}개 스킬 모두 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
