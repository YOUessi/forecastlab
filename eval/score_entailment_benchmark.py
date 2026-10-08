"""Score entailment judge predictions against the hard-negative benchmark."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

LABELS = ["entailed", "partially_entailed", "not_entailed", "unclear"]


def wilson(successes: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = successes / n
    d = 1 + z*z/n
    center = (p + z*z/(2*n)) / d
    margin = z * math.sqrt((p*(1-p)/n) + (z*z/(4*n*n))) / d
    return [max(0.0, center-margin), min(1.0, center+margin)]


def key(row: dict) -> str:
    return row.get("id") or f"{row.get('case_id')}::{row.get('finding_id')}::{row.get('claim')}"


def confusion(gold_rows: list[dict], pred_rows: list[dict]) -> dict:
    pmap = {key(r): r for r in pred_rows}
    matrix = {g: {p: 0 for p in LABELS} for g in LABELS}
    missing = []
    for row in gold_rows:
        k = key(row)
        pred = pmap.get(k)
        if not pred:
            missing.append(k)
            continue
        plabel = pred["judge"]["label"]
        matrix[row["gold_label"]][plabel] += 1
    return {"matrix": matrix, "missing": missing}


def score(benchmark: dict, judged: dict, thresholds=(0.5, 0.7, 0.8, 0.9, 0.95), split: str = "all") -> dict:
    gold = benchmark["rows"]
    if split != "all":
        gold = [row for row in gold if row.get("split") == split]
    pmap = {key(r): r for r in judged.get("rows", [])}
    common = [r for r in gold if key(r) in pmap]
    if not common:
        raise ValueError("benchmark/judge files have no overlapping rows")

    exact = sum(pmap[key(r)]["judge"]["label"] == r["gold_label"] for r in common)
    strict_positive = {"entailed"}
    rows_by_phenomenon = {}
    for row in common:
        rows_by_phenomenon.setdefault(row["phenomenon"], []).append(row)

    threshold_rows = []
    for threshold in thresholds:
        accepted = []
        for row in common:
            j = pmap[key(row)]["judge"]
            if j["label"] == "entailed" and float(j.get("confidence", 0)) >= threshold:
                accepted.append(row)
        strict = sum(r["gold_label"] in strict_positive for r in accepted)
        false_accepts = [r for r in accepted if r["gold_label"] not in strict_positive]
        true_supported = [r for r in common if r["gold_label"] in strict_positive]
        supported_accepted = [r for r in accepted if r["gold_label"] in strict_positive]
        threshold_rows.append({
            "threshold": threshold,
            "accepted": len(accepted),
            "acceptance_rate": len(accepted)/len(common),
            "strict_support_among_accepted": strict/len(accepted) if accepted else None,
            "strict_support_wilson95": wilson(strict, len(accepted)),
            "supported_recall": len(supported_accepted)/len(true_supported) if true_supported else None,
            "false_accept_count": len(false_accepts),
            "false_accepts": [{"id": r["id"], "case_id": r["case_id"], "finding_id": r["finding_id"],
                                "gold_label": r["gold_label"], "phenomenon": r["phenomenon"]}
                               for r in false_accepts[:50]],
        })

    by_phenomenon = {}
    for phenomenon, rows in sorted(rows_by_phenomenon.items()):
        correct = sum(pmap[key(r)]["judge"]["label"] == r["gold_label"] for r in rows)
        strict_rows = [r for r in rows if r["gold_label"] == "entailed"]
        accepted = [r for r in rows if pmap[key(r)]["judge"]["label"] == "entailed"]
        strict_accepted = sum(r["gold_label"] == "entailed" for r in accepted)
        by_phenomenon[phenomenon] = {
            "n": len(rows),
            "exact_accuracy": correct/len(rows),
            "entailed_gold": len(strict_rows),
            "judge_accepted": len(accepted),
            "accept_precision": strict_accepted/len(accepted) if accepted else None,
        }

    conf = confusion(common, judged.get("rows", []))
    return {
        "benchmark_rows": len(gold),
        "split": split,
        "judged_rows": len(common),
        "coverage": len(common)/len(gold),
        "four_class_exact_accuracy": exact/len(common),
        "confusion_matrix": conf["matrix"],
        "missing_prediction_ids": conf["missing"],
        "thresholds": threshold_rows,
        "by_phenomenon": by_phenomenon,
        "judge_model": judged.get("judge_model"),
        "judge_type": judged.get("judge_type", "llm"),
        "independent_model": judged.get("independent_model"),
        "same_as_generator_model": judged.get("same_as_generator_model"),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("benchmark", type=Path)
    p.add_argument("judged", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--split", choices=["all", "train", "calibration", "test"], default="all")
    args = p.parse_args()
    result = score(
        json.loads(args.benchmark.read_text(encoding="utf-8")),
        json.loads(args.judged.read_text(encoding="utf-8")),
        split=args.split,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
