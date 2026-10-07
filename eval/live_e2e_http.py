"""Drive ForecastLab through its HTTP API for real model + real online-search E2E tests."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib import error, parse, request
from uuid import uuid4

TERMINAL = {"completed", "insufficient_evidence", "scenario_only", "partial", "failed", "interrupted"}

CASES = [
    {
        "id": "L01-python315",
        "category": "tech",
        "question": "Python 3.15 是否会在 2026 年 11 月 15 日 23:59 UTC 前在 python.org 正式下载页发布稳定正式版？",
        "resolve_by": "2026-11-15T23:59:00Z",
        "resolution_rule": "若 python.org 官方下载页在截止时间前出现 Python 3.15 稳定正式版（非 alpha、beta 或 release candidate），则为“是”，否则为“否”。",
        "resolution_source": "https://www.python.org/downloads/",
        "clarification_answer": "以 python.org 正式下载页的稳定正式版为准，不包括 alpha、beta 或 release candidate。",
    },
    {
        "id": "L02-arsenal-top4",
        "category": "sport",
        "question": "阿森纳是否会在 2026/27 英超赛季最终积分榜中排名前四？",
        "resolve_by": "2027-06-30T23:59:00Z",
        "resolution_rule": "以英超官网发布的 2026/27 赛季最终积分榜为准；阿森纳最终名次为第 1 至第 4 名则为“是”，否则为“否”。",
        "resolution_source": "https://www.premierleague.com/tables",
        "clarification_answer": "只按英超官网最终积分榜的第 1 至第 4 名判定，不采用阶段排名。",
    },
    {
        "id": "L03-artemis3",
        "category": "public",
        "question": "NASA Artemis III 是否会在 2027 年 12 月 31 日前完成载人月球着陆任务，并由 NASA 官方确认任务完成？",
        "resolve_by": "2027-12-31T23:59:00Z",
        "resolution_rule": "若 NASA 官方在截止时间前确认 Artemis III 已完成载人月球着陆任务，则为“是”，否则为“否”。",
        "resolution_source": "https://www.nasa.gov/mission/artemis-iii/",
        "clarification_answer": "以 NASA 官方确认 Artemis III 完成载人月球着陆任务为准。",
    },
]


def call(base: str, method: str, path: str, payload=None, timeout=60):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(base + path, data=body, method=method,
                          headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try: detail = json.loads(raw)
        except Exception: detail = {"body": raw[:1000]}
        raise RuntimeError(f"HTTP {exc.code} {method} {path}: {detail}") from exc


def citation_check(base: str, run: dict) -> dict:
    assessment = run.get("evidence_assessment") or {}
    evidence = {e["id"]: e for e in run.get("evidence", [])}
    checked = 0
    failures = []
    cache = {}
    for finding in assessment.get("findings", []):
        for citation in finding.get("citations", []):
            eid = citation["evidence_id"]
            if eid not in evidence:
                failures.append(f"{finding['id']} references missing {eid}")
                continue
            if eid not in cache:
                _, cache[eid] = call(base, "GET", f"/api/runs/{run['run_id']}/evidence/{parse.quote(eid)}/passages")
            source = cache[eid]
            quote = citation["quote"]
            start, end = citation["start"], citation["end"]
            if source.get("snapshot_hash") != citation.get("snapshot_hash"):
                failures.append(f"{finding['id']}/{eid} snapshot hash mismatch")
            if source.get("text", "")[start:end] != quote:
                failures.append(f"{finding['id']}/{eid} exact quote offset mismatch")
            paragraphs = {p["paragraph_id"]: p for p in source.get("passages", [])}
            para = paragraphs.get(citation.get("paragraph_id"))
            if para is None or quote not in para.get("text", ""):
                failures.append(f"{finding['id']}/{eid} paragraph/quote mismatch")
            checked += 1
    return {"citations_checked": checked, "citation_failures": failures, "all_valid": not failures}


def final_reference_check(run: dict) -> dict:
    forecast = run.get("forecast") or {}
    world = run.get("world") or {}
    valid_e = {x["id"] for x in run.get("evidence", [])}
    valid_h = {x["id"] for x in world.get("assumptions", [])}
    valid_s = {x["id"] for x in run.get("simulation", [])}
    invalid = []
    for side in ("supporting", "opposing"):
        for idx, claim in enumerate(forecast.get(side, []) or []):
            for field, values, valid in (
                ("evidence_ids", claim.get("evidence_ids", []), valid_e),
                ("assumption_ids", claim.get("assumption_ids", []), valid_h),
                ("simulation_ids", claim.get("simulation_ids", []), valid_s),
            ):
                bad = sorted(set(values) - valid)
                if bad: invalid.append({"side": side, "claim_index": idx, "field": field, "invalid": bad})
    f_ids = {f["id"] for f in (run.get("evidence_assessment") or {}).get("findings", [])}
    leaked_f = []
    for side in ("supporting", "opposing"):
        for idx, claim in enumerate(forecast.get(side, []) or []):
            text = json.dumps(claim, ensure_ascii=False)
            leaked = sorted(fid for fid in f_ids if fid in text)
            if leaked: leaked_f.append({"side": side, "claim_index": idx, "finding_ids": leaked})
    return {"invalid_final_references": invalid, "finding_ids_leaked_to_final_claims": leaked_f,
            "all_valid": not invalid and not leaked_f}


def run_case(base: str, case: dict, as_of: str, poll_seconds: float, timeout_seconds: int) -> dict:
    started = time.time()
    question = {
        "question": case["question"], "as_of": as_of, "resolve_by": case["resolve_by"],
        "resolution_rule": case["resolution_rule"], "resolution_source": case["resolution_source"],
        "mode": "binary", "user_assumptions": [],
    }
    _, frame = call(base, "POST", "/api/questions/analyze", {"question": question, "operation_id": uuid4().hex}, timeout=90)
    framing_revisions = 1
    clarification_log = []
    if frame["status"] == "needs_clarification":
        open_items = [c for c in frame["clarifications"] if c["status"] == "open" and c["blocking"]]
        clarification_log = [{"id": c["id"], "field": c["field"], "question": c["question"],
                              "answer": case["clarification_answer"]} for c in open_items]
        _, frame = call(base, "POST", "/api/questions/analyze", {
            "question": frame["proposed_spec"], "draft_id": frame["draft_id"],
            "expected_revision": frame["revision"], "operation_id": uuid4().hex,
            "answers": [{"clarification_id": c["id"], "answer": case["clarification_answer"]} for c in open_items],
        }, timeout=90)
        framing_revisions += 1
    if frame["status"] != "ready_for_confirmation":
        return {"id": case["id"], "category": case["category"], "status": "framing_not_ready",
                "framing": frame, "clarifications": clarification_log, "elapsed_seconds": round(time.time()-started, 3)}

    decisions = []
    for premise in frame["premises"]:
        decisions.append({"premise_id": premise["id"],
                          "user_review": "retained" if premise["origin"] == "user_explicit" else "rejected",
                          "treatment": "to_verify"})
    _, confirmation = call(base, "POST", f"/api/questions/{frame['draft_id']}/confirm", {
        "expected_revision": frame["revision"], "decisions": decisions,
    })
    _, created = call(base, "POST", "/api/runs", {"confirmation_id": confirmation["confirmation_id"], "evidence_mode": "online"})
    run_id = created["run_id"]
    deadline = time.time() + timeout_seconds
    while True:
        _, run = call(base, "GET", f"/api/runs/{run_id}")
        if run["status"] in TERMINAL:
            break
        if time.time() >= deadline:
            raise TimeoutError(f"{case['id']} timed out with status={run['status']} stage={run['stage']}")
        time.sleep(poll_seconds)

    assessment = run.get("evidence_assessment") or {}
    world = run.get("world") or {}
    review = run.get("review") or {}
    forecast = run.get("forecast") or {}
    retrieval = run.get("retrieval_result") or {}
    evidence = run.get("evidence", [])
    body_count = sum(e.get("content_kind") == "body" for e in evidence)
    cite = citation_check(base, run)
    refs = final_reference_check(run)
    return {
        "id": case["id"], "category": case["category"], "question": case["question"],
        "run_id": run_id, "status": run["status"], "stage": run["stage"],
        "framing_revisions": framing_revisions, "clarifications": clarification_log,
        "premises": [{"id": p["id"], "origin": p["origin"], "content": p["content"],
                      "user_review": next((d["user_review"] for d in decisions if d["premise_id"] == p["id"]), None)}
                     for p in frame["premises"]],
        "retrieval_tasks": [{"id": t["id"], "purpose": t["purpose"], "query": t["query"],
                             "target_premise_ids": t["target_premise_ids"]} for t in frame["retrieval_plan"]],
        "retrieval_status": retrieval.get("status"),
        "retrieval_log": retrieval.get("retrieval_log", []),
        "retrieval_exclusions": retrieval.get("exclusions", []),
        "evidence_count": len(evidence), "body_count": body_count,
        "snippet_only_count": len(evidence)-body_count,
        "finding_count": len(assessment.get("findings", [])),
        "rejected_finding_count": len(assessment.get("rejected_findings", [])),
        "findings_validated": assessment.get("findings_validated"),
        "conflict_count": len(assessment.get("conflict_details", [])),
        "gap_count": len(assessment.get("gap_details", [])),
        "actor_count": len(world.get("actors", [])),
        "assumption_count": len(world.get("assumptions", [])),
        "action_count": len(run.get("actions", [])),
        "simulation_step_count": len(run.get("simulation", [])),
        "review_status": review.get("status"), "probability_basis": review.get("probability_basis"),
        "forecast_status": forecast.get("status"), "probabilities": forecast.get("probabilities"),
        "citation_validation": cite, "final_reference_validation": refs,
        "usage": run.get("usage"), "stage_durations": run.get("stage_durations"),
        "resume_count": run.get("resume_count"), "errors": run.get("errors", []),
        "elapsed_seconds": round(time.time()-started, 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--poll-seconds", type=float, default=1.0)
    ap.add_argument("--timeout-seconds", type=int, default=420)
    args = ap.parse_args()
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = []
    for i, case in enumerate(CASES, 1):
        print(f"[{i}/{len(CASES)}] {case['id']} start", flush=True)
        try:
            row = run_case(args.base, case, as_of, args.poll_seconds, args.timeout_seconds)
        except Exception as exc:
            row = {"id": case["id"], "category": case["category"], "question": case["question"],
                   "status": "harness_error", "error_type": type(exc).__name__, "error": str(exc)[:1000]}
        rows.append(row)
        print(f"[{i}/{len(CASES)}] {case['id']} status={row['status']} evidence={row.get('evidence_count')} findings={row.get('finding_count')} calls={(row.get('usage') or {}).get('calls')}", flush=True)
    success = [r for r in rows if r.get("status") in {"completed", "insufficient_evidence", "scenario_only", "partial"}]
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(), "kind": "real_live_http_e2e",
        "base": args.base, "as_of": as_of, "cases": len(rows),
        "terminal_runs": len(success), "completed": sum(r.get("status") == "completed" for r in rows),
        "hard_failures": sum(r.get("status") in {"failed", "interrupted", "harness_error", "framing_not_ready"} for r in rows),
        "all_citations_valid": all((r.get("citation_validation") or {}).get("all_valid", False) for r in success) if success else False,
        "all_final_refs_valid": all((r.get("final_reference_validation") or {}).get("all_valid", False) for r in success) if success else False,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["cases","terminal_runs","completed","hard_failures","all_citations_valid","all_final_refs_valid"]}, ensure_ascii=False, indent=2), flush=True)

if __name__ == "__main__":
    main()
