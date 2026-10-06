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
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "eval" / "suites" / "forecastlab-v2.json"


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def evidence_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("evidence") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("证据包必须是数组或包含 evidence 数组")
    return items


def _cutoff_proof_time(item: dict) -> datetime | None:
    """Accept only explicitly verifiable immutable snapshot proofs.

    A client-provided retrieved_at alone is never enough. The proof must tie its timestamp
    to an immutable URL identity: a Wayback capture timestamp or a fixed Git commit SHA.
    """
    proof = item.get("cutoff_proof")
    if not isinstance(proof, dict):
        return None
    kind = proof.get("kind")
    timestamp = proof.get("timestamp")
    reference = str(proof.get("reference") or "")
    source_url = str(item.get("source_url") or "")
    if not timestamp or kind not in {"web_archive", "git_commit"}:
        return None
    try:
        proved_at = parse_ts(timestamp)
    except ValueError:
        return None

    if kind == "web_archive":
        match = re.search(r"web\.archive\.org/web/(\d{14})/", source_url)
        if not match or reference != source_url:
            return None
        raw = match.group(1)
        encoded = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=proved_at.tzinfo)
        return proved_at if encoded == proved_at else None

    blob = re.search(r"github\.com/[^/]+/[^/]+/blob/([0-9a-f]{40})/", source_url, re.I)
    commit = re.search(r"github\.com/[^/]+/[^/]+/commit/([0-9a-f]{40})(?:$|[/?#])", reference, re.I)
    if not blob or not commit or blob.group(1).lower() != commit.group(1).lower():
        return None
    return proved_at


def publication_date_coverage(items: list[dict], as_of: datetime) -> dict:
    """Describe whether each historical evidence item proves availability by the cutoff."""
    published_known = 0
    proof_known = 0
    availability_known = 0
    after_cutoff = 0
    missing = []
    invalid_proofs = []
    for item in items:
        location = item.get("source_url") or item.get("title") or "?"
        published = item.get("published_at")
        published_ok = False
        if published:
            published_known += 1
            try:
                published_time = parse_ts(published)
                if published_time > as_of:
                    after_cutoff += 1
                else:
                    published_ok = True
            except ValueError:
                invalid_proofs.append(location)

        proof_present = item.get("cutoff_proof") is not None
        proved_at = _cutoff_proof_time(item)
        proof_ok = False
        if proved_at is not None:
            proof_known += 1
            if proved_at > as_of:
                after_cutoff += 1
            else:
                proof_ok = True
        elif proof_present:
            invalid_proofs.append(location)

        if published_ok or proof_ok:
            availability_known += 1
        else:
            missing.append(location)

    total = len(items)
    return {
        "known": published_known,
        "published_known": published_known,
        "cutoff_proof_known": proof_known,
        "availability_known": availability_known,
        "total": total,
        "missing": missing,
        "invalid_proofs": list(dict.fromkeys(invalid_proofs)),
        "after_cutoff": after_cutoff,
        "coverage": (published_known / total) if total else 0.0,
        "availability_coverage": (availability_known / total) if total else 0.0,
        "strict_cutoff_ready": bool(total) and availability_known == total and after_cutoff == 0 and not invalid_proofs,
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
            "evidence_count": 0, "published_known": 0, "cutoff_proof_known": 0, "availability_known": 0, "published_total": 0,
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
            "evidence_count": 0, "published_known": 0, "cutoff_proof_known": 0, "availability_known": 0, "published_total": 0,
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
    elif not dates["strict_cutoff_ready"]:
        warnings.append(
            f"cutoff provenance 覆盖 {dates['availability_known']}/{dates['total']} "
            f"(published_at {dates['published_known']}/{dates['total']}, immutable proof {dates['cutoff_proof_known']}/{dates['total']})；"
            "无法证明全部历史证据在 as_of 前已可获得"
        )
    if dates["invalid_proofs"]:
        problems.append("cutoff_proof 无法验证：" + "、".join(dates["invalid_proofs"]))

    status = "broken" if problems else "needs_review" if warnings else "ready"
    return {
        "id": cid,
        "category": case.get("category", "unknown"),
        "as_of": as_of.isoformat(),
        "outcome": case.get("outcome"),
        "evidence_count": len(items),
        "published_known": dates["published_known"],
        "cutoff_proof_known": dates["cutoff_proof_known"],
        "availability_known": dates["availability_known"],
        "published_total": dates["total"],
        "publication_coverage": round(dates["coverage"], 6),
        "availability_coverage": round(dates["availability_coverage"], 6),
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
                f"proof={row.get('cutoff_proof_known', 0)}/{row['published_total']} "
                f"available={row.get('availability_known', row['published_known'])}/{row['published_total']} "
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
