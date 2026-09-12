#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${PORT:-8501}"

export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"

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
trap cleanup EXIT INT TERM

handle_signal() {
    exit 130
}
trap handle_signal INT TERM

printf 'Starting backend at http://127.0.0.1:%s\n' "$BACKEND_PORT"
(
    cd "$ROOT_DIR/backend"
    exec "$PYTHON_BIN" -m uvicorn app:app --host 127.0.0.1 --port "$BACKEND_PORT"
) &
backend_pid=$!

cd "$ROOT_DIR/frontend"
printf 'Starting frontend at http://0.0.0.0:%s\n' "$FRONTEND_PORT"
"$PYTHON_BIN" -m streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port "$FRONTEND_PORT" \
    --server.headless true &
frontend_pid=$!

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

exit "$status"
