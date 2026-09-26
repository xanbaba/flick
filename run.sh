#!/usr/bin/env bash
# Launches P1 sensor, P2 stimulus, P3 backend and P4 frontend.
# See ARCHITECTURE.md section 3.2 for the process table.
set -euo pipefail

cd "$(dirname "$0")"

PIDS=()

cleanup() {
    echo "Stopping all processes..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

echo "Starting P1 sensor..."
uv run python -m sensor.main &
PIDS+=("$!")

echo "Starting P2 stimulus..."
uv run python -m stimulus.main &
PIDS+=("$!")

echo "Starting P3 backend..."
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 &
PIDS+=("$!")

echo "Starting P4 frontend..."
(cd frontend && npm run dev) &
PIDS+=("$!")

wait
