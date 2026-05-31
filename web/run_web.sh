#!/bin/bash
#
# DEPRECATED: use ../run.sh from the repo root instead.
#
# This used to bring up just the web UI. That logic now lives in the root-level
# run.sh, which also runs the C++ lobby server and does a port pre-flight. This
# shim keeps the old entrypoint (and CI) working by delegating to run.sh in
# web-only mode (SKIP_SERVER defaults to 1 here so no Bazel/C++ server is
# needed). Pass SKIP_SERVER=0 to also start the lobby server, or just call
# ../run.sh directly.
#
# Usage / env vars are unchanged: HOST, PORT, RESULTS_DIR, SKIP_BUILD.

exec env SKIP_SERVER="${SKIP_SERVER:-1}" \
    "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/run.sh" "$@"
