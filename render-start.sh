#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-8501}"

cd "$ROOT_DIR/backend"
exec "$PYTHON_BIN" -m uvicorn app:app --host 0.0.0.0 --port "$PORT"
