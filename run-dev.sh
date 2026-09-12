#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${PYTHON_BIN:-}" ]]; then
    if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
        PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi
fi
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-8501}"
BACKEND_URL_HOST="${BACKEND_URL_HOST:-127.0.0.1}"

if [[ ! -x "$PYTHON_BIN" ]] && ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf 'Python executable not found: %s\n' "$PYTHON_BIN" >&2
    exit 1
fi

export BACKEND_URL="${BACKEND_URL:-http://${BACKEND_URL_HOST}:${BACKEND_PORT}}"

backend_pid=""
frontend_pid=""
stopping=0

cleanup() {
    trap - EXIT INT TERM
    if [[ "$stopping" -eq 1 ]]; then
        return
    fi
    stopping=1
    [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
    [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}

handle_signal() {
    exit 130
}

trap cleanup EXIT INT TERM
trap handle_signal INT TERM

printf 'Starting backend at http://%s:%s\n' "$BACKEND_HOST" "$BACKEND_PORT"
(
    cd "$ROOT_DIR/backend"
    exec "$PYTHON_BIN" -m uvicorn app:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
) &
backend_pid=$!

printf 'Starting frontend at http://%s:%s\n' "$FRONTEND_HOST" "$FRONTEND_PORT"
(
    cd "$ROOT_DIR/frontend"
    exec "$PYTHON_BIN" -m streamlit run app.py --server.address "$FRONTEND_HOST" --server.port "$FRONTEND_PORT"
) &
frontend_pid=$!

printf 'Both services are running. Press Ctrl+C to stop them.\n'

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
    sleep 1
done

if ! kill -0 "$backend_pid" 2>/dev/null; then
    if wait "$backend_pid"; then status=0; else status=$?; fi
    printf 'Backend stopped with exit code %s.\n' "$status" >&2
else
    if wait "$frontend_pid"; then status=0; else status=$?; fi
    printf 'Frontend stopped with exit code %s.\n' "$status" >&2
fi

if [[ "$status" -ne 0 ]]; then
    printf 'A service stopped unexpectedly.\n' >&2
fi

exit "$status"
