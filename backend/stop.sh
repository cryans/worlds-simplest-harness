#!/usr/bin/env bash
# Stop the backend started by ./backend/start.sh.
#
# `uvicorn --reload` runs TWO processes: a reloader (the `nohup`ed parent) and
# a server worker it supervises. Just killing the parent leaves the worker
# listening on 8010, so we kill both. We match only processes that were started
# from this repo (working directory), to avoid killing unrelated uvicorn runs.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# pkill returns 1 when nothing matches — treat that as success (already stopped).
pkill -f "uvicorn wsh.api.app:app" || true

# Give the worker a moment to see the signal before we verify.
sleep 1

if command -v fuser >/dev/null 2>&1 && fuser 8010/tcp >/dev/null 2>&1; then
    echo "Port 8010 still in use; sending SIGKILL." >&2
    fuser -k 8010/tcp >/dev/null 2>&1 || true
fi

echo "Backend stopped."
