"""Build a larger hard-negative entailment benchmark from prior human-role audits.

The benchmark combines unique natural labelled claim/quote pairs from five historical
Agent 2 audits, then creates exactly one controlled contradiction for every natural
supported row. Generated negatives alter the claim only; exact quotes stay frozen.

This avoids LLM-generated gold labels and makes every synthetic negative reproducible.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

SOURCES = [
    "experiment-2026-10-08-agent2-boundary-v2/results/reviewer2-labeled.json",
    "experiment-2026-10-08-agent2-boundary-v1/results/reviewer2-labeled.json",
    "experiment-2026-10-07-agent12-semantic/results/agent2-audit-labeled-after.json",
    "experiment-2026-10-07-agent12-semantic/results/agent2-audit-labeled-before.json",
    "experiment-2026-10-07-agent12-robustness/results/agent2-finding-quote-audit-labeled.json",
]

LABEL_MAP = {
    "supported": "entailed",
    "partially_supported": "partially_entailed",
    "unsupported": "not_entailed",
    "unclear": "unclear",
}

NO_DIGIT_MUTATIONS = [
    ("并非全部", "全部", "quantifier_flip"),
    ("卫冕冠军", "非卫冕冠军", "entity_status_flip"),
    ("法国居首", "法国居第二", "ranking_flip"),
    ("宣布推出", "尚未宣布推出", "event_negation"),
    ("表示反对", "表示支持", "stance_flip"),
    ("必须推动", "无需推动", "modality_flip"),
    ("已进入活动极大期", "尚未进入活动极大期", "event_negation"),
    ("公布了", "从未公布", "event_negation"),
]


def quote_text(row: dict) -> str:
    return "\n".join(c.get("quote", "") for c in row.get("citations", []))


def stable_key(row: dict) -> str:
    return json.dumps([row.get("claim", ""), quote_text(row)], ensure_ascii=False, separators=(",", ":"))



def mutate_number(claim: str) -> tuple[str, str] | None:
    match = re.search(r"\d+(?:\.\d+)?", claim)
    if not match:
        return None
    token = match.group(0)
    if "." in token:
        whole, frac = token.split(".", 1)
        replacement = f"{int(whole) + 1}.{frac}"
    else:
        replacement = str(int(token) + 1)
    return claim[:match.start()] + replacement + claim[match.end():], "numeric_shift"


def contradiction(row: dict) -> tuple[str, str]:
    numeric = mutate_number(row["claim"])
    if numeric is not None:
        return numeric
    for old, new, phenomenon in NO_DIGIT_MUTATIONS:
        if old in row["claim"]:
            return row["claim"].replace(old, new, 1), phenomenon
    raise ValueError(f"no deterministic contradiction operator for {row['case_id']} {row['finding_id']}: {row['claim']}")


def load_natural() -> list[dict]:
    unique: dict[str, dict] = {}
    for source in SOURCES:
        data = json.loads((ROOT / source).read_text(encoding="utf-8"))
        for row in data.get("rows", []):
            key = stable_key(row)
            if key in unique:
                continue
            item = {
                "id": "",
                "origin": "human_role_audit",
                "source_dataset": source,
                "case_id": row["case_id"],
                "finding_id": row["finding_id"],
                "category": row.get("category", "unknown"),
                "claim": row["claim"],
                "quotes": [c["quote"] for c in row.get("citations", [])],
                "gold_label": LABEL_MAP[row["human_label"]],
                "phenomenon": "natural",
                "mutation": None,
                "human_label": row["human_label"],
                "human_notes": row.get("human_notes", ""),
            }
            unique[key] = item
    return list(unique.values())


def build() -> dict:
    natural = load_natural()
    for index, item in enumerate(natural, 1):
        item["id"] = f"natural-{index:04d}"
    generated = []
    for item in natural:
        if item["gold_label"] != "entailed":
            continue
        row = {
            "case_id": item["case_id"],
            "finding_id": item["finding_id"],
            "claim": item["claim"],
            "citations": [{"quote": q} for q in item["quotes"]],
        }
        mutated_claim, phenomenon = contradiction(row)
        mutated = dict(item)
        mutated.update({
            "id": f"hardneg-{len(generated)+1:04d}",
            "origin": "controlled_hard_negative",
            "source_dataset": item["source_dataset"],
            "claim": mutated_claim,
            "gold_label": "not_entailed",
            "phenomenon": phenomenon,
            "mutation": {
                "operator": phenomenon,
                "base_id": item["id"],
                "base_claim": item["claim"],
            },
            "human_label": None,
            "human_notes": "Controlled contradiction generated from a human-supported base; quote is unchanged.",
        })
        generated.append(mutated)

    rows = natural + generated
    counts = {}
    phenomena = {}
    for row in rows:
        counts[row["gold_label"]] = counts.get(row["gold_label"], 0) + 1
        phenomena[row["phenomenon"]] = phenomena.get(row["phenomenon"], 0) + 1
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": "ForecastLab Agent 2 exact-quote entailment benchmark: natural human-role audit pairs plus reproducible controlled contradictions.",
        "source_files": SOURCES,
        "row_count": len(rows),
        "label_counts": counts,
        "phenomenon_counts": phenomena,
        "rows": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT / "eval/benchmarks/agent2-entailment-hard-v1.json")
    args = p.parse_args()
    result = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "row_count": result["row_count"],
        "label_counts": result["label_counts"],
        "phenomenon_counts": result["phenomenon_counts"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
