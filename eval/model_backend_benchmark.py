"""Benchmark an OpenAI-compatible model backend used by ForecastLab.

Measures transport/inference performance only. It does not score semantic quality.
No credentials are accepted on the command line; provider credentials come from env/.env.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openai import OpenAI
from app import config


from app.benchmarking import summarize_rows

def resolved_settings(args) -> dict[str, object]:
    env = dict(os.environ)
    if args.provider:
        env["FORECASTLAB_MODEL_PROVIDER"] = args.provider
    settings = config.resolve_model_settings(env)
    if args.base_url:
        settings["base_url"] = args.base_url.rstrip("/")
    if args.model:
        settings["model"] = args.model
    return settings


def run_one(client: OpenAI, *, model: str, case: dict, request_index: int) -> dict:
    started = time.perf_counter()
    ttft = None
    usage = None
    chunks: list[str] = []
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": case["system"]},
                {"role": "user", "content": case["user"]},
            ],
            temperature=0,
            max_tokens=int(case.get("max_tokens", 512)),
            stream=True,
            stream_options={"include_usage": True},
        )
        for event in stream:
            if getattr(event, "usage", None):
                usage = event.usage
            for choice in getattr(event, "choices", []) or []:
                content = getattr(getattr(choice, "delta", None), "content", None)
                if content:
                    if ttft is None:
                        ttft = time.perf_counter() - started
                    chunks.append(content)
        ended = time.perf_counter()
        total = ended - started
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        output_tokens = getattr(usage, "completion_tokens", None) if usage else None
        tpot_ms = None
        decode_tok_s = None
        if ttft is not None and output_tokens and output_tokens > 1 and total > ttft:
            decode_seconds = total - ttft
            tpot_ms = decode_seconds * 1000 / (output_tokens - 1)
            decode_tok_s = (output_tokens - 1) / decode_seconds
        return {
            "case_id": case["id"],
            "request_index": request_index,
            "status": "ok",
            "ttft_ms": round(ttft * 1000, 3) if ttft is not None else None,
            "total_ms": round(total * 1000, 3),
            "tpot_ms": round(tpot_ms, 3) if tpot_ms is not None else None,
            "decode_tok_s": round(decode_tok_s, 3) if decode_tok_s is not None else None,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": output_tokens,
            "response_chars": len("".join(chunks)),
        }
    except Exception as exc:
        return {
            "case_id": case["id"],
            "request_index": request_index,
            "status": "failed",
            "error_type": type(exc).__name__,
            "total_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def run_case(client: OpenAI, *, model: str, case: dict, concurrency: int, repeat: int) -> dict:
    rows = []
    batches = []
    for iteration in range(repeat):
        batch_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [
                pool.submit(run_one, client, model=model, case=case, request_index=iteration * concurrency + i)
                for i in range(concurrency)
            ]
            batch_rows = [f.result() for f in futures]
        batch_seconds = time.perf_counter() - batch_started
        rows.extend(batch_rows)
        prompt = sum(r.get("prompt_tokens") or 0 for r in batch_rows if r.get("status") == "ok")
        completion = sum(r.get("completion_tokens") or 0 for r in batch_rows if r.get("status") == "ok")
        batches.append({
            "iteration": iteration,
            "elapsed_ms": round(batch_seconds * 1000, 3),
            "prompt_tokens": prompt or None,
            "completion_tokens": completion or None,
            "total_tok_s": round((prompt + completion) / batch_seconds, 3) if prompt + completion else None,
            "output_tok_s": round(completion / batch_seconds, 3) if completion else None,
        })
    return {
        "case_id": case["id"],
        "description": case.get("description", ""),
        "concurrency": concurrency,
        "repeat": repeat,
        "summary": summarize_rows(rows),
        "batches": batches,
        "requests": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("examples/moorethreads/inference-cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=["qwen", "deepseek", "vllm_mt"])
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    if args.repeat < 1 or any(c < 1 for c in args.concurrency):
        parser.error("repeat and concurrency must be >= 1")

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        parser.error("cases must be a non-empty JSON array")

    settings = resolved_settings(args)
    if bool(settings["requires_key"]) and not settings["api_key"]:
        parser.error(f"{settings['provider']} requires its API key environment variable")

    client = OpenAI(
        api_key=str(settings["api_key"]),
        base_url=str(settings["base_url"]),
        timeout=float(settings["timeout_seconds"]),
        max_retries=0,
    )

    results = []
    for case in cases:
        for concurrency in args.concurrency:
            results.append(
                run_case(
                    client,
                    model=str(settings["model"]),
                    case=deepcopy(case),
                    concurrency=concurrency,
                    repeat=args.repeat,
                )
            )

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "transport_inference_benchmark",
        "semantic_quality": "not_evaluated",
        "provider": settings["provider"],
        "base_url": settings["base_url"],
        "model": settings["model"],
        "results": results,
        "limitations": [
            "TTFT/TPOT measure the configured endpoint plus network transport.",
            "Token metrics are null if the provider does not return streaming usage.",
            "This benchmark does not establish Agent 1/2 semantic quality.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output} ({len(results)} case/concurrency groups)")


if __name__ == "__main__":
    main()
