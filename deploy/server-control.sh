#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
pidfile="$root/../forecastlab-server.pid"
logfile="$root/../forecastlab-server.log"
owned_running() {
  test -f "$pidfile" || return 1
  pid="$(cat "$pidfile")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  test "$(stat -c %u "/proc/$pid" 2>/dev/null)" = "$(id -u)" || return 1
  test "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$root" || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'uvicorn app.api:app'
}
case "${1:-status}" in
  start)
    if owned_running; then echo "ForecastLab is already running."; exit 0; fi
    cd "$root"
    export NO_PROXY=127.0.0.1,localhost
    umask 077
    nohup .venv/bin/python -m uvicorn app.api:app --app-dir backend --host 127.0.0.1 --port 18765 >> "$logfile" 2>&1 < /dev/null &
    echo $! > "$pidfile"
    echo "ForecastLab started on 127.0.0.1:18765; inspect $logfile."
    ;;
  stop)
    if owned_running; then
      kill "$pid"
      for _ in {1..20}; do owned_running || break; sleep .5; done
      if owned_running; then kill -KILL "$pid"; fi
      : > "$pidfile"
      echo "ForecastLab stopped."
    else echo "No owned ForecastLab process found."; fi
    ;;
  status)
    if owned_running; then curl -fsS http://127.0.0.1:18765/api/health; else echo "ForecastLab is stopped."; exit 1; fi
    ;;
  *) echo "Usage: $0 start|stop|status"; exit 2 ;;
esac
