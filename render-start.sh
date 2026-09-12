#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${PORT:-8501}"

export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"

backend_pid=""
cleanup() {
    trap - EXIT INT TERM
    [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
    cd "$ROOT_DIR/backend"
    exec "$PYTHON_BIN" -m uvicorn app:app --host 127.0.0.1 --port "$BACKEND_PORT"
) &
backend_pid=$!

cd "$ROOT_DIR/frontend"
exec "$PYTHON_BIN" -m streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port "$FRONTEND_PORT" \
    --server.headless true
