#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-8501}"

backend_pid=""
frontend_pid=""

cleanup() {
    trap - EXIT INT TERM
    [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
    [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

printf 'Starting backend at http://localhost:%s\n' "$BACKEND_PORT"
(
    cd "$ROOT_DIR/backend"
    exec "$PYTHON_BIN" -m uvicorn app:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
) &
backend_pid=$!

printf 'Starting frontend at http://localhost:%s\n' "$FRONTEND_PORT"
(
    cd "$ROOT_DIR/frontend"
    exec "$PYTHON_BIN" -m streamlit run app.py --server.address 0.0.0.0 --server.port "$FRONTEND_PORT"
) &
frontend_pid=$!

printf 'Both services are running. Press Ctrl+C to stop them.\n'
wait -n "$backend_pid" "$frontend_pid"
status=$?

if [[ "$status" -ne 0 ]]; then
    printf 'A service stopped unexpectedly with exit code %s.\n' "$status" >&2
fi

exit "$status"
