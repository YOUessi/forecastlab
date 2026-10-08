"""Run a frozen case suite through three arms and write one results table.

Arms
    full          the whole ForecastLab pipeline (six stages, review, repair)
    single_agent  one model call with the same frozen evidence pack
    no_evidence   one model call with the question only (model knowledge only)

All three arms answer the same questions, so ``score_table.py`` can compare them on
identical rows. Each case/arm pair gets a fresh ModelClient, because the client
enforces a per-run budget (FORECASTLAB_MAX_CALLS / _MAX_SECONDS).

Usage
    python eval/run_suite.py suites/forecastlab-v1.json --out results/suite-001.json
    python eval/score_table.py results/suite-001.json --group-by category
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config  # noqa: E402
from app.graph import execute  # noqa: E402
from app.llm import ModelClient  # noqa: E402
from app.schemas import ImportedEvidence, QuestionSpec, RunRecord  # noqa: E402
from app.sources import normalize_import  # noqa: E402
from app.storage import RunStore  # noqa: E402
from single_agent import predict  # noqa: E402

ARMS = ("full", "single_agent", "no_evidence")
REPO_ROOT = Path(__file__).resolve().parents[1]


def case_evidence(case: dict) -> list[dict]:
    """Evidence may be inline, or point at a frozen pack file.

    Keeping each pack in its own file is what makes a case reproducible: the
    file is hashed and frozen before the run, so the evidence cannot drift.
    """
    if isinstance(case.get("evidence"), list):
        return case["evidence"]
    reference = case.get("evidence_file")
    if not reference:
        return []
    path = Path(reference)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        raise SystemExit(f"案例 {case.get('id')} 的证据包不存在：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("evidence") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise SystemExit(f"案例 {case.get('id')} 的证据包必须是数组或含 evidence 数组")
    return items


def load_suite(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise SystemExit("套件必须是 JSON 数组，或含 cases 数组的对象")
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict) or "id" not in case or "question" not in case:
            raise SystemExit(f"第 {index} 个案例缺少 id 或 question")
        if case.get("outcome") not in (0, 1):
            raise SystemExit(f"案例 {case.get('id')} 的 outcome 必须是 0 或 1")
    return (data if isinstance(data, dict) else {}), cases


def yes_outcome(question: QuestionSpec) -> str:
    """outcome == 1 means the first listed outcome happened."""
    return question.outcomes[0]


def run_full_arm(case: dict, data_dir: Path) -> dict:
    question = QuestionSpec.model_validate(case["question"])
    imported = [ImportedEvidence.model_validate(item) for item in case_evidence(case)]
    evidence = normalize_import(imported, question) if imported else []
    store = RunStore(data_dir)
    record = RunRecord(run_id=f"eval_{case['id']}_{uuid4().hex[:6]}", question=question,
                       evidence_mode="import", model=config.MODEL_NAME)
    store.save(record)
    started = time.monotonic()
    execute(record, evidence, store)
    finished = store.get(record.run_id)
    probabilities = finished.forecast.probabilities if finished.forecast else None
    shadow = finished.shadow_forecast
    return {
        "full_p": probabilities.get(yes_outcome(question)) if probabilities else None,
        "full_status": finished.status,
        "shadow_full_p": (shadow.probabilities or {}).get(yes_outcome(question)) if shadow and shadow.probabilities else None,
        "shadow_full_status": shadow.status if shadow else None,
        "full_seconds": round(time.monotonic() - started, 2),
        "full_calls": finished.usage.get("calls"),
        "full_tokens": (finished.usage.get("prompt_tokens") or 0) + (finished.usage.get("completion_tokens") or 0),
        "run_id": finished.run_id,
        "errors": " | ".join(finished.errors),
    }


def run_single_arm(case: dict, *, with_evidence: bool) -> dict:
    question = QuestionSpec.model_validate(case["question"])
    imported = [ImportedEvidence.model_validate(item) for item in case_evidence(case)]
    evidence = normalize_import(imported, question) if imported else []
    client = ModelClient()
    try:
        result, metrics = predict(question, evidence, client, with_evidence=with_evidence)
        return {
            "p": float(result.probability_yes),
            "seconds": metrics["elapsed_seconds"],
            "calls": metrics["usage"].get("calls"),
            "tokens": (metrics["usage"].get("prompt_tokens") or 0) + (metrics["usage"].get("completion_tokens") or 0),
            "answer_yes_means": result.conclusion,
            "errors": "",
        }
    except Exception as exc:  # noqa: BLE001 - the suite must survive one bad case
        return {"p": None, "seconds": None, "calls": None, "tokens": None, "answer_yes_means": "", "errors": f"{type(exc).__name__}: {exc}"[:300]}


def main():
    parser = argparse.ArgumentParser(description="Run a frozen evaluation suite through three arms")
    parser.add_argument("suite", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="结果表输出路径")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "eval")
    parser.add_argument("--only", default=",".join(ARMS), help=f"只跑指定臂，逗号分隔，可选 {','.join(ARMS)}")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 个案例")
    parser.add_argument("--dry-run", action="store_true", help="只校验套件并打印计划，不调用模型")
    args = parser.parse_args()

    meta, cases = load_suite(args.suite)
    arms = [arm.strip() for arm in args.only.split(",") if arm.strip()]
    unknown = set(arms) - set(ARMS)
    if unknown:
        raise SystemExit(f"未知的臂：{', '.join(sorted(unknown))}")
    if args.limit:
        cases = cases[: args.limit]

    frozen = meta.get("frozen", {})
    if args.dry_run:
        print(json.dumps({
            "suite": meta.get("name", args.suite.stem),
            "cases": len(cases),
            "arms": arms,
            "categories": sorted({str(case.get("category", "unknown")) for case in cases}),
            "model": config.MODEL_NAME,
            "model_key_configured": bool(config.MODEL_API_KEY),
            "max_calls_per_run": config.MAX_CALLS,
            "estimated_model_calls_upper_bound": len(cases) * (
                (config.MAX_CALLS if "full" in arms else 0) + sum(1 for arm in arms if arm != "full")
            ),
        }, ensure_ascii=False, indent=2))
        return

    if not config.MODEL_API_KEY:
        raise SystemExit("未配置模型密钥，无法运行评测；请先在 .env 里设置 QWEN 或 DEEPSEEK 的 key")

    started_at = datetime.now(timezone.utc)
    rows = []
    for index, case in enumerate(cases, 1):
        question = QuestionSpec.model_validate(case["question"])
        row = {
            "id": case["id"],
            "category": case.get("category", "unknown"),
            "outcome": case["outcome"],
            "yes_outcome": yes_outcome(question),
        }
        if "full" in arms:
            try:
                row.update(run_full_arm(case, args.data_dir))
            except Exception as exc:  # noqa: BLE001 - keep the suite going
                row.update({"full_p": None, "full_status": "crashed", "errors": f"{type(exc).__name__}: {exc}"[:300]})
        if "single_agent" in arms:
            result = run_single_arm(case, with_evidence=True)
            row.update({"single_agent_p": result["p"], "single_agent_seconds": result["seconds"],
                        "single_agent_calls": result["calls"], "single_agent_tokens": result["tokens"]})
            if result["errors"]:
                row["errors"] = (row.get("errors", "") + " | " + result["errors"]).strip(" |")
        if "no_evidence" in arms:
            result = run_single_arm(case, with_evidence=False)
            row.update({"no_evidence_p": result["p"], "no_evidence_seconds": result["seconds"],
                        "no_evidence_calls": result["calls"], "no_evidence_tokens": result["tokens"]})
            if result["errors"]:
                row["errors"] = (row.get("errors", "") + " | " + result["errors"]).strip(" |")
        rows.append(row)
        print(f"[{index}/{len(cases)}] {case['id']} outcome={case['outcome']} "
              f"full={row.get('full_p')} single={row.get('single_agent_p')} none={row.get('no_evidence_p')}", flush=True)

    output = {
        "suite": meta.get("name", args.suite.stem),
        "frozen": {**frozen, "model": config.MODEL_NAME, "prompt_version": "v2",
                   "max_calls": config.MAX_CALLS, "max_seconds": config.MAX_SECONDS},
        "arms": arms,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(rows),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写入 {args.out}")


if __name__ == "__main__":
    main()
