"""Combine NLI and independent LLM judge outputs for entailment gating."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def key(row: dict) -> str:
    return row.get("id") or f"{row.get('case_id')}::{row.get('finding_id')}::{row.get('claim')}"


def combine(benchmark: dict, nli: dict, llm: dict, *, nli_accept: float, nli_reject: float,
            llm_accept: float, policy: str) -> dict:
    nmap = {key(r): r for r in nli.get("rows", [])}
    lmap = {key(r): r for r in llm.get("rows", [])}
    out = []
    for row in benchmark["rows"]:
        k = key(row)
        nr = nmap.get(k)
        lr = lmap.get(k)
        if not nr or not lr:
            continue
        nj = nr["judge"]
        lj = lr["judge"]
        ep = float(nj.get("entailment_probability", nj.get("confidence", 0)))
        cp = float(nj.get("contradiction_probability", 0))

        if policy == "agreement":
            accept = (
                nj["label"] == "entailed" and ep >= nli_accept
                and lj["label"] == "entailed" and float(lj.get("confidence", 0)) >= llm_accept
            )
            label = "entailed" if accept else (
                "not_entailed" if nj["label"] == "not_entailed" or lj["label"] == "not_entailed"
                else "partially_entailed"
            )
            route = "agreement"
        elif policy == "nli_then_llm":
            if nj["label"] == "entailed" and ep >= nli_accept:
                label, route = "entailed", "nli_accept"
            elif nj["label"] == "not_entailed" and cp >= nli_reject:
                label, route = "not_entailed", "nli_reject"
            else:
                label, route = lj["label"], "llm_fallback"
        else:
            raise ValueError(f"unknown policy: {policy}")

        item = json.loads(json.dumps(row, ensure_ascii=False))
        item["judge"] = {
            "label": label,
            "confidence": (
                min(ep, float(lj.get("confidence", 0))) if policy == "agreement"
                else ep if route.startswith("nli_") else float(lj.get("confidence", 0))
            ),
            "route": route,
            "nli_label": nj["label"],
            "nli_entailment_probability": ep,
            "nli_contradiction_probability": cp,
            "llm_label": lj["label"],
            "llm_confidence": float(lj.get("confidence", 0)),
        }
        out.append(item)

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "judge_model": f"cascade:{nli.get('judge_model')}+{llm.get('judge_model')}",
        "judge_type": f"cascade:{policy}",
        "independent_model": bool(nli.get("independent_model")) and bool(llm.get("independent_model")),
        "same_as_generator_model": bool(llm.get("same_as_generator_model")),
        "policy": policy,
        "thresholds": {
            "nli_accept": nli_accept,
            "nli_reject": nli_reject,
            "llm_accept": llm_accept,
        },
        "rows": out,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("benchmark", type=Path)
    p.add_argument("nli", type=Path)
    p.add_argument("llm", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--policy", choices=["agreement", "nli_then_llm"], default="agreement")
    p.add_argument("--nli-accept", type=float, default=0.90)
    p.add_argument("--nli-reject", type=float, default=0.90)
    p.add_argument("--llm-accept", type=float, default=0.90)
    args = p.parse_args()
    result = combine(
        json.loads(args.benchmark.read_text(encoding="utf-8")),
        json.loads(args.nli.read_text(encoding="utf-8")),
        json.loads(args.llm.read_text(encoding="utf-8")),
        nli_accept=args.nli_accept,
        nli_reject=args.nli_reject,
        llm_accept=args.llm_accept,
        policy=args.policy,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(result["rows"]), "policy": args.policy, "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
