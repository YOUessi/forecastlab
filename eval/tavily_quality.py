"""Run a real Tavily retrieval-quality evaluation through ForecastLab's production retriever.

This measures retrieval behavior only. It does not call an LLM or score forecast accuracy.
TAVILY_API_KEY must come from the environment/.env and is never written to the report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import subprocess
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import config
from app.schemas import QuestionSpec, RetrievalTask, utcnow
from app.sources import retrieve_evidence


def _host(url: str | None) -> str:
    if not url:
        return ""
    return (urlparse(str(url)).hostname or "").lower().removeprefix("www.")


def _domain_matches(host: str, expected: str) -> bool:
    expected = expected.lower().removeprefix("www.")
    return host == expected or host.endswith("." + expected)


def _git_head(root: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 6) if d else None


def summarize_case(case: dict, result) -> dict:
    evidence = result.evidence
    hosts = [_host(str(item.source_url) if item.source_url else None) for item in evidence]
    hosts = [h for h in hosts if h]
    expected_domains = [str(x).lower() for x in case.get("expected_authoritative_domains", [])]
    found_expected = sorted({domain for domain in expected_domains if any(_domain_matches(host, domain) for host in hosts)})
    task_ids = {task["id"] for task in case["tasks"]}
    covered_tasks = {qid for item in evidence for qid in item.query_ids if qid in task_ids}
    body_count = sum(item.content_kind == "body" for item in evidence)
    snippet_count = sum(item.source_type == "snippet_only" or item.content_kind == "snippet" for item in evidence)
    date_count = sum(any((item.published_at, item.updated_at, item.event_at)) for item in evidence)
    truncated_count = sum(bool(item.content_truncated) for item in evidence)
    alias_count = sum(max(0, len(item.aliases) - 1) for item in evidence)
    possible_same = sum(len(item.possible_same_source) for item in evidence) // 2
    logs = [log.model_dump(mode="json") for log in result.retrieval_log]
    successes = sum(log.status == "success" for log in result.retrieval_log)
    empties = sum(log.status == "empty" for log in result.retrieval_log)
    failures = sum(log.status == "failed" for log in result.retrieval_log)
    return {
        "id": case["id"],
        "category": case.get("category", "unknown"),
        "question": case["question"],
        "status": result.status,
        "selected_evidence": len(evidence),
        "task_count": len(task_ids),
        "task_successes": successes,
        "task_empty": empties,
        "task_failures": failures,
        "query_coverage": _ratio(len(covered_tasks), len(task_ids)),
        "body_count": body_count,
        "body_rate": _ratio(body_count, len(evidence)),
        "snippet_only_count": snippet_count,
        "snippet_only_rate": _ratio(snippet_count, len(evidence)),
        "date_metadata_count": date_count,
        "date_metadata_rate": _ratio(date_count, len(evidence)),
        "content_truncated_count": truncated_count,
        "unique_domain_count": len(set(hosts)),
        "unique_domain_rate": _ratio(len(set(hosts)), len(evidence)),
        "source_group_count": len({item.source_group for item in evidence if item.source_group}),
        "duplicate_aliases": alias_count,
        "possible_same_source_pairs": possible_same,
        "exclusion_count": len(result.exclusions),
        "expected_authoritative_domains": expected_domains,
        "authoritative_domains_found": found_expected,
        "authoritative_hit": bool(found_expected) if expected_domains else None,
        "authoritative_recall": _ratio(len(found_expected), len(expected_domains)) if expected_domains else None,
        "retrieval_log": logs,
        "exclusions": result.exclusions,
        "evidence": [
            {
                "evidence_id": item.id,
                "title": item.title,
                "url": str(item.source_url) if item.source_url else None,
                "host": _host(str(item.source_url) if item.source_url else None),
                "publisher": item.publisher,
                "source_type": item.source_type,
                "content_kind": item.content_kind,
                "content_truncated": item.content_truncated,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "event_at": item.event_at.isoformat() if item.event_at else None,
                "query_ids": item.query_ids,
                "source_group": item.source_group,
                "source_group_basis": item.source_group_basis,
                "possible_same_source": item.possible_same_source,
                "aliases": [alias.model_dump(mode="json") for alias in item.aliases],
                "excerpt": item.excerpt,
            }
            for item in evidence
        ],
    }


def summarize(rows: list[dict]) -> dict:
    evidence = [item for row in rows for item in row["evidence"]]
    task_count = sum(row["task_count"] for row in rows)
    task_successes = sum(row["task_successes"] for row in rows)
    body_count = sum(row["body_count"] for row in rows)
    date_count = sum(row["date_metadata_count"] for row in rows)
    snippets = sum(row["snippet_only_count"] for row in rows)
    authoritative = [row for row in rows if row["authoritative_hit"] is not None]
    return {
        "cases": len(rows),
        "completed": sum(row["status"] == "completed" for row in rows),
        "partial": sum(row["status"] == "partial" for row in rows),
        "failed": sum(row["status"] == "failed" for row in rows),
        "case_with_evidence_rate": _ratio(sum(row["selected_evidence"] > 0 for row in rows), len(rows)),
        "task_success_rate": _ratio(task_successes, task_count),
        "mean_query_coverage": round(sum((row["query_coverage"] or 0) for row in rows) / len(rows), 6) if rows else None,
        "selected_evidence": len(evidence),
        "mean_selected_evidence_per_case": round(len(evidence) / len(rows), 6) if rows else None,
        "body_rate": _ratio(body_count, len(evidence)),
        "snippet_only_rate": _ratio(snippets, len(evidence)),
        "date_metadata_rate": _ratio(date_count, len(evidence)),
        "authoritative_hit_rate": _ratio(sum(bool(row["authoritative_hit"]) for row in authoritative), len(authoritative)),
        "exclusions": sum(row["exclusion_count"] for row in rows),
        "duplicate_aliases": sum(row["duplicate_aliases"] for row in rows),
        "possible_same_source_pairs": sum(row["possible_same_source_pairs"] for row in rows),
    }


def make_review_sample(rows: list[dict], sample_size: int, seed: int) -> list[dict]:
    population = []
    for row in rows:
        for item in row["evidence"]:
            population.append({
                "case_id": row["id"], "category": row["category"], "question": row["question"],
                "evidence_id": item["evidence_id"], "title": item["title"], "url": item["url"],
                "host": item["host"], "source_type": item["source_type"], "content_kind": item["content_kind"],
                "excerpt": item["excerpt"],
                "relevance_label": None,
                "source_quality_label": None,
                "reviewer_notes": "",
            })
    rng = random.Random(seed)
    chosen = rng.sample(population, min(sample_size, len(population))) if population else []
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--review-output", type=Path)
    parser.add_argument("--sample-size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7606)
    args = parser.parse_args()

    if not config.TAVILY_API_KEY:
        parser.error("TAVILY_API_KEY is not configured; real Tavily evaluation was not run")
    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    cases = suite.get("cases", [])
    if not cases:
        parser.error("suite must contain at least one case")

    args.data_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, case in enumerate(cases, 1):
        question = QuestionSpec(question=case["question"], mode="scenario", as_of=utcnow())
        tasks = [RetrievalTask(**task) for task in case["tasks"]]
        try:
            result = retrieve_evidence(question, tasks, args.data_dir / case["id"])
            row = summarize_case(case, result)
        except Exception as exc:
            row = {
                "id": case["id"], "category": case.get("category", "unknown"), "question": case["question"],
                "status": "failed", "selected_evidence": 0, "task_count": len(tasks), "task_successes": 0,
                "task_empty": 0, "task_failures": len(tasks), "query_coverage": 0.0,
                "body_count": 0, "body_rate": None, "snippet_only_count": 0, "snippet_only_rate": None,
                "date_metadata_count": 0, "date_metadata_rate": None, "content_truncated_count": 0,
                "unique_domain_count": 0, "unique_domain_rate": None, "source_group_count": 0,
                "duplicate_aliases": 0, "possible_same_source_pairs": 0, "exclusion_count": 0,
                "expected_authoritative_domains": case.get("expected_authoritative_domains", []),
                "authoritative_domains_found": [], "authoritative_hit": False,
                "authoritative_recall": 0.0, "retrieval_log": [], "exclusions": [], "evidence": [],
                "error_type": type(exc).__name__, "error": str(exc)[:500],
            }
        rows.append(row)
        print(f"[{index}/{len(cases)}] {case['id']} status={row['status']} evidence={row['selected_evidence']}")

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "real_tavily_retrieval_quality",
        "suite": suite.get("suite", args.suite.stem),
        "forecastlab_commit": _git_head(Path(__file__).resolve().parents[1]),
        "provider": "tavily",
        "search_depth": "basic",
        "max_results_per_query": 8,
        "summary": summarize(rows),
        "rows": rows,
        "limitations": [
            "Results depend on the live Tavily index and can change between runs.",
            "Authoritative-domain hits are a targeted diagnostic, not a complete relevance judgment.",
            "Automatic metrics do not establish semantic relevance; use the blind review sample for manual relevance/source-quality auditing.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))

    if args.review_output:
        review = {
            "created_at": report["created_at"], "source_report": str(args.output), "seed": args.seed,
            "label_schema": {
                "relevance_label": ["relevant", "partially_relevant", "irrelevant", "unclear"],
                "source_quality_label": ["primary_authoritative", "reputable_secondary", "other", "unclear"],
            },
            "instructions": "Judge only the retrieved item shown. Do not infer from unseen page content. Fill both labels and optional notes.",
            "rows": make_review_sample(rows, args.sample_size, args.seed),
        }
        args.review_output.parent.mkdir(parents=True, exist_ok=True)
        args.review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote blind review sample: {args.review_output} ({len(review['rows'])} rows)")


if __name__ == "__main__":
    main()
