#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x ".venv/bin/python" ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e ".[dev]"
fi

if [[ ! -d "frontend/node_modules" ]]; then
  (cd frontend && npm install)
fi

backend_pid=""
frontend_pid=""

cleanup() {
  trap - EXIT INT TERM
  [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && kill "$backend_pid" 2>/dev/null || true
  wait "${frontend_pid:-}" 2>/dev/null || true
  wait "${backend_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Backend:  http://127.0.0.1:8000"
echo "API docs: http://127.0.0.1:8000/docs"
echo "Frontend: http://127.0.0.1:5173"

.venv/bin/python -m uvicorn research_report_agent.main:app \
  --host 127.0.0.1 --port 8000 &
backend_pid=$!

(
  cd frontend
  npm run dev -- --host 127.0.0.1 --port 5173
) &
frontend_pid=$!

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 0.5
done
