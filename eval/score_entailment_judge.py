"""Calibrate an entailment judge against human-labelled exact-quote audits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HUMAN_STRICT_POSITIVE = {"supported"}
JUDGE_POSITIVE = {"entailed"}


def _key(row: dict) -> tuple[str, str]:
    return row["case_id"], row["finding_id"]


def score(human: dict, judged: dict, thresholds=(0.5, 0.7, 0.8, 0.9, 0.95)) -> dict:
    hmap = {_key(r): r for r in human.get("rows", [])}
    jmap = {_key(r): r for r in judged.get("rows", [])}
    common = sorted(set(hmap) & set(jmap))
    if not common:
        raise ValueError("human/judge files have no overlapping rows")

    tp = tn = fp = fn = 0
    four_class_matches = 0
    mapped = {
        "entailed": "supported",
        "partially_entailed": "partially_supported",
        "not_entailed": "unsupported",
        "unclear": "unclear",
    }
    for key in common:
        h = hmap[key]["human_label"]
        j = jmap[key]["judge"]["label"]
        hpos = h in HUMAN_STRICT_POSITIVE
        jpos = j in JUDGE_POSITIVE
        if hpos and jpos: tp += 1
        elif hpos and not jpos: fn += 1
        elif not hpos and jpos: fp += 1
        else: tn += 1
        four_class_matches += int(mapped[j] == h)

    n = len(common)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    accuracy = (tp + tn) / n

    threshold_rows = []
    for threshold in thresholds:
        accepted = []
        for key in common:
            jr = jmap[key]["judge"]
            if jr["label"] == "entailed" and float(jr["confidence"]) >= threshold:
                accepted.append(key)
        strict = sum(hmap[k]["human_label"] == "supported" for k in accepted)
        leaks = [k for k in accepted if hmap[k]["human_label"] != "supported"]
        threshold_rows.append({
            "threshold": threshold,
            "accepted": len(accepted),
            "acceptance_rate": len(accepted) / n,
            "strict_supported_accepted": strict,
            "strict_support_among_accepted": strict / len(accepted) if accepted else None,
            "non_strict_leaks": [{"case_id": k[0], "finding_id": k[1]} for k in leaks],
        })

    return {
        "n": n,
        "binary_strict_gate": {
            "tp_supported_accept": tp,
            "tn_nonstrict_block": tn,
            "fp_nonstrict_accept": fp,
            "fn_supported_block": fn,
            "precision_of_accept": precision,
            "recall_of_supported": recall,
            "specificity_for_nonstrict": specificity,
            "accuracy": accuracy,
        },
        "four_class_exact_accuracy": four_class_matches / n,
        "thresholds": threshold_rows,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("human", type=Path)
    p.add_argument("judged", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = score(
        json.loads(args.human.read_text(encoding="utf-8")),
        json.loads(args.judged.read_text(encoding="utf-8")),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
