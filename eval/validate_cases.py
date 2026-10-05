"""Offline check of eval/cases/*.json case definitions and their evidence packs.

Does not call any model. Verifies:
  - case JSON parses and has the required fields
  - outcome is 0/1
  - evidence_file exists when declared
  - every evidence item's published_at / updated_at is <= question.as_of
  - no duplicate evidence source_url inside one pack

Usage: python eval/validate_cases.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "eval" / "cases"


def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    ok, warn, bad = [], [], []
    files = sorted(p for p in CASES.glob("C*.json") if not p.name.endswith("-evidence.json"))
    for path in files:
        case = json.loads(path.read_text(encoding="utf-8"))
        cid = case.get("id", path.stem)
        q = case.get("question", {})
        problems = []
        if case.get("outcome") not in (0, 1):
            problems.append("outcome 不是 0/1")
        as_of = parse_ts(q["as_of"])
        if parse_ts(q["resolve_by"]) <= as_of:
            problems.append("resolve_by 不晚于 as_of")
        items = []
        ref = case.get("evidence_file")
        if ref:
            epath = ROOT / ref
            if not epath.is_file():
                problems.append(f"证据包缺失 {ref}")
            else:
                items = json.loads(epath.read_text(encoding="utf-8")).get("evidence", [])
        for it in items:
            for key in ("published_at", "updated_at"):
                if it.get(key) and parse_ts(it[key]) > as_of:
                    problems.append(f"{key} 晚于 as_of: {it.get('source_url', '?')}")
        urls = [it.get("source_url") for it in items]
        if len(urls) != len(set(urls)):
            problems.append("同一证据包内有重复 source_url")
        review = case.get("review", {})
        status = review.get("evidence_status", "?")
        n = len(items)
        if n == 0:
            (bad if problems else warn).append((cid, as_of.date(), case["outcome"], n, status, review.get("confidence", "?"), "; ".join(problems)))
        elif n < 2:
            warn.append((cid, as_of.date(), case["outcome"], n, status, review.get("confidence", "?"), "; ".join(problems)))
        else:
            ok.append((cid, as_of.date(), case["outcome"], n, status, review.get("confidence", "?"), "; ".join(problems)))
    for title, rows in (("READY (>=2 evidence)", ok), ("THIN (1 evidence)", warn), ("PENDING / BROKEN", bad)):
        print(f"\n== {title}: {len(rows)} ==")
        for r in rows:
            print("  {:<34} as_of={} outcome={} n={} status={} conf={} {}".format(*r))
    print(f"\ntotal cases: {len(ok) + len(warn) + len(bad)}")


if __name__ == "__main__":
    sys.exit(main())
