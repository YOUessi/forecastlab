"""Collect reproducibility metadata for a Moore Threads benchmark run.

The collector never reads API keys. Missing GPU commands are recorded instead of treated as
ForecastLab failures so the script can also be syntax-checked on development machines.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess


COMMANDS = {
    "mthreads_gmi": ["mthreads-gmi"],
    "musa_info": ["musaInfo"],
    "vllm_version": ["vllm", "--version"],
    "python_version": ["python", "--version"],
}


def capture(command: list[str]) -> dict:
    if shutil.which(command[0]) is None:
        return {"status": "missing", "command": command}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        return {
            "status": "ok" if result.returncode == 0 else "failed",
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip()[:20000],
            "stderr": result.stderr.strip()[:4000],
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "command": command}


def git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "moorethreads_environment",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "forecastlab_commit": git_head(root),
        "commands": {name: capture(cmd) for name, cmd in COMMANDS.items()},
        "note": "No API keys or .env contents are collected.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
