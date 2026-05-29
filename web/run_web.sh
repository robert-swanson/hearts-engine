#!/bin/bash
#
# Bring up the Hearts web UI as a single process (serves /api + the built SPA).
#
# Idempotent: creates the Python venv and installs deps on first run, installs
# node modules if missing, rebuilds the frontend, then execs uvicorn.
#
# Usage:
#   web/run_web.sh                 # build + serve on 0.0.0.0:8000
#   PORT=9000 web/run_web.sh       # override port
#   SKIP_BUILD=1 web/run_web.sh    # serve existing dist without rebuilding
#
# Env vars:
#   HOST         bind address     (default 0.0.0.0)
#   PORT         bind port        (default 8000)
#   RESULTS_DIR  results location (default <repo>/results)
#   SKIP_BUILD   set to 1 to skip the npm build step

set -e

# Resolve paths relative to this script so it runs from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RESULTS_DIR="${RESULTS_DIR:-$REPO_ROOT/results}"
VENV="$BACKEND_DIR/.venv"

echo "==> Backend venv"
if [ ! -d "$VENV" ]; then
    echo "    creating venv at $VENV"
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"

echo "==> Frontend"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "    installing node modules"
    npm --prefix "$FRONTEND_DIR" install
fi
if [ "${SKIP_BUILD:-0}" != "1" ]; then
    echo "    building frontend"
    npm --prefix "$FRONTEND_DIR" run build
else
    echo "    SKIP_BUILD=1, using existing dist/"
fi

if [ ! -d "$FRONTEND_DIR/dist" ]; then
    echo "ERROR: $FRONTEND_DIR/dist not found; cannot serve the SPA." >&2
    exit 1
fi

echo "==> Serving on http://$HOST:$PORT  (RESULTS_DIR=$RESULTS_DIR)"
cd "$BACKEND_DIR"
exec env RESULTS_DIR="$RESULTS_DIR" "$VENV/bin/uvicorn" main:app --host "$HOST" --port "$PORT"
