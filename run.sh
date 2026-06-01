#!/bin/bash
#
# Run the complete Hearts dev environment in one command:
#   * the C++ Hearts "lobby" server (handles matching + live games), and
#   * the web UI (FastAPI backend + built React SPA), which talks to that server.
#
# Before starting anything, every required port is checked. If a port is already
# taken the script EARLY-EXITS and tells you exactly which process is holding it
# (PID + command) and how to free it — so the lobby server only ever launches on
# a port that has been pre-sanitized.
#
# Usage:
#   ./run.sh                      # build + run lobby server + serve web on 0.0.0.0:8000
#   PORT=9000 ./run.sh            # override the web port
#   SKIP_BUILD=1 ./run.sh         # serve the existing dist/ without rebuilding
#   SKIP_SERVER=1 ./run.sh        # web only — don't build/run the C++ lobby server
#
# Env vars:
#   HOST               web bind address        (default 0.0.0.0)
#   PORT               web bind port           (default 8000)
#   RESULTS_DIR        results location        (default <repo>/results)
#   SKIP_BUILD         set to 1 to skip the npm build
#   SKIP_SERVER        set to 1 to skip the C++ lobby server
#
# Auth (optional; controls who can see each round's private "cards passed"):
#   WEB_ADMIN_PASSWORD admin login password — sign in with a blank team to see
#                      every team's passed cards. If unset, admin login is off.
#   Team login uses the TEAMS=name:password entries in tournament_server.env;
#   a signed-in team sees only its own players' passed cards.

set -e

# Resolve paths relative to this script so it runs from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$SCRIPT_DIR/web"
BACKEND_DIR="$WEB_DIR/backend"
FRONTEND_DIR="$WEB_DIR/frontend"
CONFIG_FILE="$SCRIPT_DIR/config.env"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/results}"
VENV="$BACKEND_DIR/.venv"
RUN_SERVER=1
[ "${SKIP_SERVER:-0}" = "1" ] && RUN_SERVER=0

# The C++ lobby server reads its listen port from config.env (SERVER_PORT). The
# web backend's live-play SDK connects to that same port, so they must agree.
SERVER_PORT="${SERVER_PORT:-40405}"
if [ -f "$CONFIG_FILE" ]; then
    PARSED_PORT=$(grep "^SERVER_PORT=" "$CONFIG_FILE" 2>/dev/null | head -1 | cut -d= -f2 | tr -d '[:space:]' || true)
    [ -n "$PARSED_PORT" ] && SERVER_PORT="$PARSED_PORT"
fi

# ============================================================================
# PRE-FLIGHT — validate everything before starting any service
# ============================================================================
echo "==> Pre-flight checks"
FAILED=0

require_cmd() {  # require_cmd <command> <human label>
    if command -v "$1" &> /dev/null; then
        echo "  ✓ $2"
    else
        echo "  ✗ $2 not found in PATH"
        FAILED=1
    fi
}

require_file() {  # require_file <path> <human label>
    if [ -f "$1" ]; then
        echo "  ✓ $2"
    else
        echo "  ✗ $2 not found ($1)"
        FAILED=1
    fi
}

# Print the listener(s) on a TCP port, or nothing if it's free.
port_pids() { lsof -ti tcp:"$1" -sTCP:LISTEN 2>/dev/null || true; }

# Toolchain + project files.
require_cmd python3 "Python 3"
require_cmd npm "npm"
require_file "$BACKEND_DIR/requirements.txt" "backend requirements.txt"
require_file "$FRONTEND_DIR/package.json" "frontend package.json"
require_file "$CONFIG_FILE" "config.env"
if [ "$RUN_SERVER" = "1" ]; then
    require_cmd bazel "Bazel (needed to build the C++ lobby server)"
fi

# Port availability. Collect every conflict first so the user sees them all at
# once, with the exact process + kill command, then bail before doing any work.
PORT_CONFLICTS=()
check_port() {  # check_port <port> <label>
    local p="$1" label="$2" pids
    if ! command -v lsof &> /dev/null; then
        echo "  ⚠ Cannot verify $label (port $p): lsof not found"
        return
    fi
    pids="$(port_pids "$p")"
    if [ -z "$pids" ]; then
        echo "  ✓ $label (port $p) is free"
        return
    fi
    FAILED=1
    for pid in $pids; do
        local cmd
        cmd="$(ps -p "$pid" -o command= 2>/dev/null | sed 's/^[[:space:]]*//')"
        echo "  ✗ $label (port $p) is in use by PID $pid: ${cmd:-unknown}"
        PORT_CONFLICTS+=("port $p ($label): PID $pid — ${cmd:-unknown}")
    done
}

check_port "$PORT" "web UI"
[ "$RUN_SERVER" = "1" ] && check_port "$SERVER_PORT" "C++ lobby server"

# ---- Early exit on any failure ---------------------------------------------
if [ "$FAILED" != "0" ]; then
    echo ""
    if [ "${#PORT_CONFLICTS[@]}" -gt 0 ]; then
        echo "❌ One or more required ports are already in use:"
        echo ""
        for c in "${PORT_CONFLICTS[@]}"; do
            echo "   • $c"
        done
        # Build a de-duplicated kill command from the conflicting PIDs.
        kill_pids="$(printf '%s\n' "${PORT_CONFLICTS[@]}" | grep -oE 'PID [0-9]+' | awk '{print $2}' | sort -u | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
        echo ""
        echo "   Free them by stopping those processes, e.g.:"
        echo "       kill ${kill_pids}"
        echo "   (use 'kill -9 ${kill_pids}' if they don't stop, or set PORT=... / SERVER_PORT=... to use different ports)"
    fi
    echo ""
    echo "❌ Pre-flight failed — nothing was started. Fix the issues above and re-run."
    exit 1
fi

echo ""
echo "✅ Pre-flight passed"
echo ""

# ============================================================================
# STARTUP — only after every check passed
# ============================================================================

# --- C++ lobby server --------------------------------------------------------
if [ "$RUN_SERVER" = "1" ]; then
    echo "==> Starting Hearts C++ lobby server on pre-sanitized port $SERVER_PORT"
    cd "$SCRIPT_DIR"
    bazel run //server:server -- "$CONFIG_FILE" &
    SERVER_PID=$!
    echo "    Lobby server PID: $SERVER_PID"
    # Tear the server down when the web process (and thus this script) exits.
    trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
    sleep 2
else
    echo "==> Skipping C++ lobby server (SKIP_SERVER=1)"
fi

# --- Python backend ----------------------------------------------------------
echo "==> Setting up Python backend"
if [ ! -d "$VENV" ]; then
    echo "    Creating venv at $VENV"
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"
echo "    Backend dependencies installed"

# --- Frontend ----------------------------------------------------------------
echo "==> Setting up frontend"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "    Installing node modules"
    npm --prefix "$FRONTEND_DIR" install
fi
if [ "${SKIP_BUILD:-0}" != "1" ]; then
    echo "    Building frontend"
    npm --prefix "$FRONTEND_DIR" run build
else
    echo "    Using existing dist/ (SKIP_BUILD=1)"
fi
if [ ! -d "$FRONTEND_DIR/dist" ]; then
    echo "ERROR: $FRONTEND_DIR/dist not found; cannot serve the SPA." >&2
    exit 1
fi
echo "    Frontend ready"

echo ""
echo "==> Serving web UI on http://$HOST:$PORT  (RESULTS_DIR=$RESULTS_DIR)"
echo "Ready! Open http://localhost:$PORT in your browser"
echo ""

cd "$BACKEND_DIR"
exec env RESULTS_DIR="$RESULTS_DIR" "$VENV/bin/uvicorn" main:app --host "$HOST" --port "$PORT"
