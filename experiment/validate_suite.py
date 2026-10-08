"""Offline check of every experiment suite and its evidence packs.

Mirrors eval/validate_cases.py, but works for suites that live under experiment/.
No model is called. For each case it verifies:
  - the case parses and has the required fields
  - outcome is 0/1 and resolve_by > as_of
  - evidence_file exists and every evidence published_at/updated_at is <= as_of
  - no duplicate source_url inside one pack, and each pack has >= 2 items
Suites that declare a training-data cutoff (``frozen.cutoff_basis``) additionally
require every ``as_of`` to be >= that window, so leakage cannot creep back in.

Usage:
    python experiment/validate_suite.py                 # validate all suites
    python experiment/validate_suite.py <suite.json>    # validate one suite
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # forecastlab/
EXPERIMENT = Path(__file__).resolve().parent
CUTOFF_WINDOW_START = "2025-07-01T00:00:00Z"


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_suite(path: Path) -> int:
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    enforce_cutoff = "cutoff_basis" in (data.get("frozen") or {})
    print(f"\n== {path.relative_to(ROOT)} ({data.get('name', path.stem)}) ==")
    ok, bad = 0, 0
    for case in data["cases"]:
        problems = []
        question = case.get("question", {})
        if case.get("outcome") not in (0, 1):
            problems.append("outcome 不是 0/1")
        as_of = parse_ts(question["as_of"])
        if parse_ts(question["resolve_by"]) <= as_of:
            problems.append("resolve_by 不晚于 as_of")
        if enforce_cutoff and as_of < parse_ts(CUTOFF_WINDOW_START):
            problems.append("as_of 早于 2025-07-01（训练数据可能覆盖）")
        ref = case.get("evidence_file")
        items = []
        if ref:
            pack = ROOT / ref
            if not pack.is_file():
                problems.append(f"证据包缺失 {ref}")
            else:
                items = json.loads(pack.read_text(encoding="utf-8")).get("evidence", [])
        for item in items:
            for key in ("published_at", "updated_at"):
                if item.get(key) and parse_ts(item[key]) > as_of:
                    problems.append(f"{key} 晚于 as_of: {item.get('source_url', '?')}")
        urls = [item.get("source_url") for item in items]
        if len(urls) != len(set(urls)):
            problems.append("同一证据包内有重复 source_url")
        if len(items) < 2:
            problems.append(f"证据不足（{len(items)} 条）")
        if problems:
            bad += 1
            print(f"BAD {case['id']:<24} as_of={question['as_of'][:10]} "
                  f"outcome={case['outcome']} n={len(items)} {'; '.join(problems)}")
        else:
            ok += 1
    print(f"   -> total={len(data['cases'])} ok={ok} bad={bad}")
    return bad


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        suites = [Path(a) for a in argv[1:]]
    else:
        suites = sorted(EXPERIMENT.glob("*/suite/*.json"))
    if not suites:
        print("没有找到套件文件")
        return 1
    bad = sum(check_suite(p) for p in suites)
    print(f"\n套件数={len(suites)} 问题数={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
