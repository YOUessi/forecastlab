"""Smoke-test the configured ForecastLab model backend without exposing credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openai import OpenAI
from app import config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["qwen", "deepseek", "vllm_mt"])
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    args = parser.parse_args()

    env = dict(os.environ)
    if args.provider:
        env["FORECASTLAB_MODEL_PROVIDER"] = args.provider
    settings = config.resolve_model_settings(env)
    if args.base_url:
        settings["base_url"] = args.base_url.rstrip("/")
    if args.model:
        settings["model"] = args.model
    if bool(settings["requires_key"]) and not settings["api_key"]:
        parser.error(f"{settings['provider']} requires its API key environment variable")

    client = OpenAI(
        api_key=str(settings["api_key"]),
        base_url=str(settings["base_url"]),
        timeout=float(settings["timeout_seconds"]),
        max_retries=0,
    )

    started = time.perf_counter()
    advertised = [item.id for item in client.models.list().data]
    models_ms = round((time.perf_counter() - started) * 1000, 3)

    started = time.perf_counter()
    response = client.chat.completions.create(
        model=str(settings["model"]),
        messages=[
            {"role": "system", "content": "只输出 JSON。"},
            {"role": "user", "content": '输出 {"ok": true}。'},
        ],
        temperature=0,
        max_tokens=32,
    )
    chat_ms = round((time.perf_counter() - started) * 1000, 3)

    print(json.dumps({
        "ok": True,
        "provider": settings["provider"],
        "base_url": settings["base_url"],
        "configured_model": settings["model"],
        "advertised_models": advertised,
        "actual_model": getattr(response, "model", None),
        "models_request_ms": models_ms,
        "chat_request_ms": chat_ms,
        "usage": {
            "prompt_tokens": getattr(getattr(response, "usage", None), "prompt_tokens", None),
            "completion_tokens": getattr(getattr(response, "usage", None), "completion_tokens", None),
        },
        "content": response.choices[0].message.content,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
