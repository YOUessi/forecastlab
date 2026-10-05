#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || "$2" != "--" ]]; then
  echo "usage: $0 PROFILE_LOG -- COMMAND [ARGS...]" >&2
  exit 2
fi

PROFILE_LOG="$1"
shift 2

if ! command -v mthreads-gmi >/dev/null 2>&1; then
  echo "mthreads-gmi not found; run this wrapper on the Moore Threads GPU host." >&2
  exit 3
fi

mkdir -p "$(dirname "$PROFILE_LOG")"
: > "$PROFILE_LOG"

(
  while true; do
    printf '\n===== %s =====\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    mthreads-gmi || true
    sleep "${MT_PROFILE_INTERVAL_SECONDS:-1}"
  done
) >> "$PROFILE_LOG" 2>&1 &
MONITOR_PID=$!

cleanup() {
  kill "$MONITOR_PID" 2>/dev/null || true
  wait "$MONITOR_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$@"
