#!/usr/bin/env bash
# macOS / Linux / WSL: start API (8000) and UI (5173). Ctrl+C stops both.
set -e; cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt
[ -d frontend/node_modules ] || (cd frontend && npm install)
.venv/bin/python -m uvicorn api.main:app --port 8000 & API=$!
trap "kill $API" EXIT
cd frontend && npm run dev
