"""Score a fixed binary evaluation table without silently dropping abstentions.

Input JSON is a list of {id, category, outcome, full_p, baseline_p}. Missing
probabilities are null. Outcome is 0/1 from a documented resolution source.
"""
import argparse
import json
from pathlib import Path


def summarize(rows: list[dict], column: str) -> dict:
    settled = [r for r in rows if r.get("outcome") in (0, 1)]
    valid = [r for r in settled if isinstance(r.get(column), (float, int)) and 0 <= r[column] <= 1]
    return {
        "settled_n": len(settled),
        "valid_n": len(valid),
        "coverage": len(valid) / len(settled) if settled else None,
        "brier_on_valid": sum((r[column] - r["outcome"]) ** 2 for r in valid) / len(valid) if valid else None,
        "brier_with_half_fallback": sum(((r[column] if r in valid else .5) - r["outcome"]) ** 2 for r in settled) / len(settled) if settled else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Binary Brier and coverage for full vs single-agent baseline")
    parser.add_argument("table", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.table.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise SystemExit("输入必须是 JSON 对象数组")
    print(json.dumps({"full": summarize(rows, "full_p"), "baseline": summarize(rows, "baseline_p")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
