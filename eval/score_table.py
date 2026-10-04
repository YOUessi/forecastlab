"""Score a fixed binary evaluation table without silently dropping abstentions.

This is the new-file counterpart to the untouched ``eval/score.py``. It keeps
the flexible table handling used by ``run_suite.py`` while leaving the
repository's original scoring entry point exactly as it is on ``main``.

Input is a JSON array of objects. Required keys:

    id, category, outcome, and one or more probability columns ending in "_p"

    outcome     0 or 1, taken from a documented resolution source
    <name>_p    P(outcome == 1) for that arm, or null when the arm abstained

For every probability column the script reports:

    coverage                   answered / settled
    brier_on_valid             Brier over the rows the arm actually answered
    brier_with_half_fallback   Brier over all settled rows, abstentions scored 0.5
    brier_skill_vs_half        Brier Skill Score against an always-0.5 forecast
    brier_skill_vs_base_rate   Brier Skill Score against the climatology of the
                               answered rows (the base rate of the sample)

A Brier Skill Score is ``1 - Brier / Brier_reference``. It is only defined when
the reference itself makes a non-zero error, so rows where the reference is
perfect report null instead of a meaningless number.

Both references are computed on the same rows used for the arm's score, so a
system cannot gain skill by abstaining on the hard cases.
"""
import argparse
import json
from pathlib import Path

PROBABILITY_SUFFIX = "_p"


def is_probability(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def settled_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("outcome") in (0, 1) and not isinstance(row.get("outcome"), bool)]


def answered_rows(rows: list[dict], column: str) -> list[dict]:
    return [row for row in rows if is_probability(row.get(column))]


def probability_columns(rows: list[dict]) -> list[str]:
    """Column order follows first appearance, so reports stay readable."""
    names: list[str] = []
    for row in rows:
        for key in row:
            if key.endswith(PROBABILITY_SUFFIX) and key not in names:
                names.append(key)
    return names


def brier(rows: list[dict], column: str) -> float | None:
    if not rows:
        return None
    return sum((row[column] - row["outcome"]) ** 2 for row in rows) / len(rows)


def skill_score(score: float | None, reference: float | None) -> float | None:
    if score is None or reference is None or reference == 0:
        return None
    return 1 - score / reference


def summarize(rows: list[dict], column: str) -> dict:
    settled = settled_rows(rows)
    answered = answered_rows(settled, column)
    score = brier(answered, column)
    base_rate = sum(row["outcome"] for row in answered) / len(answered) if answered else None
    reference_half = brier([{**row, column: 0.5} for row in answered], column)
    reference_base_rate = brier([{**row, column: base_rate} for row in answered], column) if answered else None
    fallback = ([{**row, column: row[column] if is_probability(row.get(column)) else 0.5} for row in settled] if settled else [])
    return {
        "settled_n": len(settled),
        "valid_n": len(answered),
        "coverage": len(answered) / len(settled) if settled else None,
        "base_rate": base_rate,
        "brier_on_valid": score,
        "brier_with_half_fallback": brier(fallback, column),
        "brier_reference_half": reference_half,
        "brier_reference_base_rate": reference_base_rate,
        "brier_skill_vs_half": skill_score(score, reference_half),
        "brier_skill_vs_base_rate": skill_score(score, reference_base_rate),
    }


def summarize_columns(rows: list[dict], columns: list[str]) -> dict:
    return {column: summarize(rows, column) for column in columns}


def grouped(rows: list[dict], key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key, "unknown")), []).append(row)
    return dict(sorted(groups.items()))


def round_floats(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: round_floats(item) for key, item in value.items()}
    return value


def load_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    # run_suite.py writes {"suite": ..., "frozen": ..., "rows": [...]}; a bare
    # array is also accepted so hand-written tables keep working.
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SystemExit("输入必须是 JSON 对象数组")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Brier, Brier Skill Score and coverage for one or more arms")
    parser.add_argument("table", type=Path)
    parser.add_argument("--column", action="append", dest="columns", default=None,
                        help="只统计指定列，可重复；默认自动识别所有以 _p 结尾的列")
    parser.add_argument("--group-by", default=None, help="按某个字段分层统计，例如 category")
    args = parser.parse_args()

    rows = load_rows(args.table)
    columns = args.columns or probability_columns(rows)
    if not columns:
        raise SystemExit("没有找到以 _p 结尾的概率列")

    report = {
        "n_rows": len(rows),
        "n_settled": len(settled_rows(rows)),
        "columns": summarize_columns(rows, columns),
    }
    if args.group_by:
        report["group_by"] = args.group_by
        report["groups"] = {
            name: {"n_rows": len(items), "columns": summarize_columns(items, columns)}
            for name, items in grouped(rows, args.group_by).items()
        }
    print(json.dumps(round_floats(report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
