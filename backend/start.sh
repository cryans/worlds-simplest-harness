#!/usr/bin/env bash
# Start the backend with durable logging. Run from anywhere; paths resolve to
# the script's own directory, so it works whether you `cd backend` or call it
# as `backend/start.sh`.
#
#   ./backend/start.sh        # or: cd backend && ./start.sh
#
# Logs go to <repo>/logs/uvicorn.log (gitignored). Stop with ./backend/stop.sh
# (which kills both the reloader *and* the server worker it supervises).
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$(cd "$BACKEND_DIR/.." && pwd)/logs"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache-wsh}"

mkdir -p "$LOG_DIR"

# `uv run` needs a writable cache dir; the default ~/.cache/uv can be read-only
# in sandboxed/containerized environments. Use /tmp (matching docs/smoke-test.md)
# unless the caller already set one.
export UV_CACHE_DIR

echo "Starting backend → ${LOG_DIR}/uvicorn.log"
nohup uv run uvicorn wsh.api.app:app --reload --port 8010 \
  > "${LOG_DIR}/uvicorn.log" 2>&1 &

echo "Started (pid $!). Logs: ${LOG_DIR}/uvicorn.log"
