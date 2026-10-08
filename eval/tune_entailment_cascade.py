"""Tune NLI + LLM cascade thresholds on dev, then evaluate once on held-out test."""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import cascade_entailment_judges as cascade
import score_entailment_benchmark as scoring

GRID = (0.5, 0.7, 0.8, 0.9, 0.95)


def threshold_row(score: dict, threshold: float = 0.5) -> dict:
    return next(row for row in score["thresholds"] if row["threshold"] == threshold)


def candidate_key(item: dict, target_precision: float, min_recall: float):
    row = item["dev_gate"]
    precision = row["strict_support_among_accepted"] or 0.0
    recall = row["supported_recall"] or 0.0
    meets = precision >= target_precision and recall >= min_recall
    return (
        1 if meets else 0,
        precision if meets else precision,
        recall,
        row["acceptance_rate"],
    )


def evaluate(benchmark: dict, nli: dict, llm: dict, *, policy: str,
             target_precision: float, min_recall: float) -> dict:
    candidates = []
    if policy == "agreement":
        configs = (
            {"nli_accept": na, "nli_reject": 0.9, "llm_accept": la}
            for na, la in itertools.product(GRID, GRID)
        )
    else:
        configs = (
            {"nli_accept": na, "nli_reject": nr, "llm_accept": la}
            for na, nr, la in itertools.product(GRID, GRID, GRID)
        )

    for cfg in configs:
        combined = cascade.combine(benchmark, nli, llm, policy=policy, **cfg)
        dev = scoring.score(benchmark, combined, thresholds=(0.5,), split="dev")
        candidates.append({
            "config": cfg,
            "dev_gate": threshold_row(dev),
        })

    best = max(candidates, key=lambda x: candidate_key(x, target_precision, min_recall))
    final_combined = cascade.combine(benchmark, nli, llm, policy=policy, **best["config"])
    dev = scoring.score(benchmark, final_combined, thresholds=(0.5,), split="dev")
    test = scoring.score(benchmark, final_combined, thresholds=(0.5,), split="test")
    dev_gate = threshold_row(dev)
    test_gate = threshold_row(test)
    return {
        "policy": policy,
        "target_precision": target_precision,
        "min_recall": min_recall,
        "selected_config": best["config"],
        "dev": dev,
        "test": test,
        "dev_meets_target": (
            (dev_gate["strict_support_among_accepted"] or 0) >= target_precision
            and (dev_gate["supported_recall"] or 0) >= min_recall
        ),
        "test_meets_target": (
            (test_gate["strict_support_among_accepted"] or 0) >= target_precision
            and (test_gate["supported_recall"] or 0) >= min_recall
        ),
        "candidate_count": len(candidates),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("benchmark", type=Path)
    p.add_argument("nli", type=Path)
    p.add_argument("llm", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--target-precision", type=float, default=0.95)
    p.add_argument("--min-recall", type=float, default=0.90)
    args = p.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    nli = json.loads(args.nli.read_text(encoding="utf-8"))
    llm = json.loads(args.llm.read_text(encoding="utf-8"))
    result = {
        "agreement": evaluate(
            benchmark, nli, llm, policy="agreement",
            target_precision=args.target_precision, min_recall=args.min_recall,
        ),
        "nli_then_llm": evaluate(
            benchmark, nli, llm, policy="nli_then_llm",
            target_precision=args.target_precision, min_recall=args.min_recall,
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    compact = {}
    for policy, data in result.items():
        compact[policy] = {
            "selected_config": data["selected_config"],
            "dev_meets_target": data["dev_meets_target"],
            "test_meets_target": data["test_meets_target"],
            "dev_gate": data["dev"]["thresholds"][0],
            "test_gate": data["test"]["thresholds"][0],
        }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
