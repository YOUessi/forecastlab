"""Offline validation for a frozen ForecastLab evaluation suite.

This command never calls a model. It validates the actual suite file rather than scanning
for per-case JSON files that may not exist.

Checks:
  - case JSON structure and binary outcome
  - resolve_by is later than as_of
  - evidence_file exists and parses
  - known published_at / updated_at do not exceed the question cutoff
  - duplicate source URLs inside a pack
  - publication-date coverage for historical cutoff provenance

Missing published_at is reported as NEEDS REVIEW rather than a hard error. A historical
backtest cannot claim strict cutoff provenance until every used source has a verifiable
publication timestamp (or the evaluation protocol explicitly records a different frozen-
snapshot basis).
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "eval" / "suites" / "forecastlab-v1.json"


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def evidence_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("evidence") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("证据包必须是数组或包含 evidence 数组")
    return items


def publication_date_coverage(items: list[dict], as_of: datetime) -> dict:
    """Describe whether a historical evidence pack proves availability by the cutoff."""
    known = 0
    after_cutoff = 0
    missing = []
    for item in items:
        published = item.get("published_at")
        if not published:
            missing.append(item.get("source_url") or item.get("title") or "?")
            continue
        known += 1
        if parse_ts(published) > as_of:
            after_cutoff += 1
    total = len(items)
    return {
        "known": known,
        "total": total,
        "missing": missing,
        "after_cutoff": after_cutoff,
        "coverage": (known / total) if total else 0.0,
        "strict_cutoff_ready": bool(total) and known == total and after_cutoff == 0,
    }


def validate_case(case: dict) -> dict:
    cid = str(case.get("id") or "?")
    problems: list[str] = []
    warnings: list[str] = []

    if case.get("outcome") not in (0, 1):
        problems.append("outcome 不是 0/1")

    question = case.get("question")
    if not isinstance(question, dict):
        return {
            "id": cid, "category": case.get("category", "unknown"),
            "evidence_count": 0, "published_known": 0, "published_total": 0,
            "strict_cutoff_ready": False, "problems": ["question 缺失或不是对象"],
            "warnings": [], "status": "broken",
        }

    try:
        as_of = parse_ts(question["as_of"])
        resolve_by = parse_ts(question["resolve_by"])
        if resolve_by <= as_of:
            problems.append("resolve_by 不晚于 as_of")
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "id": cid, "category": case.get("category", "unknown"),
            "evidence_count": 0, "published_known": 0, "published_total": 0,
            "strict_cutoff_ready": False,
            "problems": [f"问题时间字段无效：{type(exc).__name__}"],
            "warnings": [], "status": "broken",
        }

    items: list[dict] = []
    ref = case.get("evidence_file")
    if not ref:
        warnings.append("未声明 evidence_file")
    else:
        path = Path(ref)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            problems.append(f"证据包缺失 {ref}")
        else:
            try:
                items = evidence_items(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                problems.append(f"证据包无法解析：{type(exc).__name__}")

    dates = publication_date_coverage(items, as_of)

    for item in items:
        for key in ("published_at", "updated_at"):
            value = item.get(key)
            if value:
                try:
                    if parse_ts(value) > as_of:
                        problems.append(
                            f"{key} 晚于 as_of: {item.get('source_url') or item.get('title') or '?'}"
                        )
                except ValueError:
                    problems.append(
                        f"{key} 不是合法时间: {item.get('source_url') or item.get('title') or '?'}"
                    )

    urls = [item.get("source_url") for item in items if item.get("source_url")]
    if len(urls) != len(set(urls)):
        problems.append("同一证据包内有重复 source_url")

    if not items:
        warnings.append("证据包为空")
    elif dates["known"] < dates["total"]:
        warnings.append(
            f"published_at 覆盖 {dates['known']}/{dates['total']}；"
            "无法证明全部历史证据在 as_of 前已可获得"
        )

    status = "broken" if problems else "needs_review" if warnings else "ready"
    return {
        "id": cid,
        "category": case.get("category", "unknown"),
        "as_of": as_of.isoformat(),
        "outcome": case.get("outcome"),
        "evidence_count": len(items),
        "published_known": dates["known"],
        "published_total": dates["total"],
        "publication_coverage": round(dates["coverage"], 6),
        "strict_cutoff_ready": dates["strict_cutoff_ready"] and not problems,
        "problems": problems,
        "warnings": warnings,
        "status": status,
    }


def validate_suite(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("suite 必须是非空数组或包含 cases 数组的对象")
    rows = [validate_case(case) for case in cases]
    counts = {
        name: sum(row["status"] == name for row in rows)
        for name in ("ready", "needs_review", "broken")
    }
    return {
        "suite": data.get("name", path.stem) if isinstance(data, dict) else path.stem,
        "case_count": len(rows),
        "strict_cutoff_ready": sum(bool(row["strict_cutoff_ready"]) for row in rows),
        "status_counts": counts,
        "cases": rows,
    }


def print_report(report: dict) -> None:
    labels = {
        "ready": "READY",
        "needs_review": "NEEDS REVIEW",
        "broken": "BROKEN",
    }
    for status in ("ready", "needs_review", "broken"):
        rows = [row for row in report["cases"] if row["status"] == status]
        print(f"\n== {labels[status]}: {len(rows)} ==")
        for row in rows:
            note = "; ".join([*row["problems"], *row["warnings"]])
            print(
                f"  {row['id']:<34} category={row['category']:<7} "
                f"n={row['evidence_count']} published={row['published_known']}/{row['published_total']} "
                f"cutoff_ready={'yes' if row['strict_cutoff_ready'] else 'no'} {note}"
            )
    print(f"\nsuite: {report['suite']}")
    print(f"total cases: {report['case_count']}")
    print(
        "strict cutoff-ready cases: "
        f"{report['strict_cutoff_ready']}/{report['case_count']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", nargs="?", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--json", dest="json_output", type=Path)
    args = parser.parse_args()

    try:
        report = validate_suite(args.suite)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {type(exc).__name__}: {exc}")
        return 2

    print_report(report)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 1 if report["status_counts"]["broken"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
